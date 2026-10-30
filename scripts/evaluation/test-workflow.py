#!/usr/bin/env python3
"""Synthetic trust-boundary checks; no real candidates or human annotations are used."""
import copy
from concurrent.futures import ThreadPoolExecutor
import hashlib
import http.client
import io
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.parse
import zlib

import workflow


def png(color):
    def chunk(kind, body):
        return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 2, 1, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(b'\0' + bytes(color) * 2)) + chunk(b'IEND', b''))


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='scriptor-synthetic-annotations-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.images = {'synthetic-one.png': png((255, 0, 0)), 'synthetic-two.png': png((0, 255, 0))}
        items = []
        for index, (name, body) in enumerate(self.images.items()):
            items.append({'id': name.removesuffix('.png'), 'source_filename': name,
                          'source_sha256': hashlib.sha256(body).hexdigest(), 'source_sha1': hashlib.sha1(body).hexdigest(),
                          'source_bytes': len(body), 'source_url': 'https://upload.wikimedia.org/synthetic-tests/' + name,
                          'group_id': f'synthetic-group-{index}', 'split': 'held_out' if index == 0 else 'development',
                          'strata': ['synthetic fixture only'], 'rights': {'license': 'CC0-1.0',
                              'attribution': 'Generated test PNG; no real source or human annotation.',
                              'source_url': 'https://example.test/synthetic-fixture', 'license_url': 'https://creativecommons.org/publicdomain/zero/1.0/'}})
        self.catalog = {'schema': 'modavis-scriptor.candidate-set/v1', 'status': 'unreviewed', 'items': items}
        self.catalog_file = self.root / 'catalog.json'
        self.catalog_file.write_bytes(workflow.canonical(self.catalog))
        self.workspace = workflow.ensure_workspace(self.root / 'workspace', self.catalog)
        (self.workspace / 'sources').mkdir()
        for name, body in self.images.items():
            (self.workspace / 'sources' / name).write_bytes(body)
        self.store = workflow.AnnotationStore(self.workspace, self.catalog)
        self.item = self.catalog['items'][0]['id']
        self.readers = ['Synthetic reader A', 'Synthetic reader B']
        self.adjudicator = 'Synthetic adjudicator C'

    def payload(self, reviewer=None, **changes):
        value = {'reviewer': reviewer or self.readers[0], 'item_id': self.item, 'expected_revision': 0,
                 'complete': True, 'human_reviewed': True, 'protocol': 'Synthetic test protocol; not actual independent human review.',
                 'regions': [{'id': 'synthetic-label', 'bbox_normalized': [0, 0, 1, 1], 'text': 'Ö 8′',
                              'protected_terms': ['Ö'], 'rationale': 'Synthetic image assessment for testing only.'}]}
        value.update(changes)
        return value

    def independent(self):
        return [self.store.save(self.payload(reader)) for reader in self.readers]

    def adjudicated(self):
        self.independent()
        return self.store.save(self.payload(self.adjudicator, adjudication={'reviewers': self.readers,
            'rationale': 'Synthetic adjudication explanation for exercising provenance; no real human decision.'}))

    def freeze(self, output=None, **changes):
        values = {'readers': self.readers, 'adjudicator': self.adjudicator, 'split': 'held_out',
                  'output': output or self.root / 'synthetic-gold.json'}
        values.update(changes)
        return workflow.freeze(self.workspace, self.catalog, **values)


class CatalogAndCollection(Fixture):
    def test_catalog_rejects_duplicate_ids_sources_and_group_leakage(self):
        self.assertEqual(workflow.catalog_at(self.catalog_file), self.catalog)
        for change in ('id', 'source', 'filename', 'group', 'status'):
            with self.subTest(change=change):
                candidate = copy.deepcopy(self.catalog)
                if change == 'id': candidate['items'][1]['id'] = candidate['items'][0]['id']
                if change == 'source': candidate['items'][1]['source_sha256'] = candidate['items'][0]['source_sha256']
                if change == 'filename': candidate['items'][1]['source_filename'] = candidate['items'][0]['source_filename']
                if change == 'group': candidate['items'][1]['group_id'] = candidate['items'][0]['group_id']
                if change == 'status': candidate['status'] = 'approved'
                self.catalog_file.write_bytes(workflow.canonical(candidate))
                with self.assertRaises(ValueError): workflow.catalog_at(self.catalog_file)

    def test_catalog_rejects_unsafe_identifiers_urls_and_duplicate_json_keys(self):
        for value in ('../private', '/absolute', 'a/b', '..', ''):
            with self.subTest(identifier=value):
                candidate = copy.deepcopy(self.catalog); candidate['items'][0]['id'] = value
                self.catalog_file.write_bytes(workflow.canonical(candidate))
                with self.assertRaises(ValueError): workflow.catalog_at(self.catalog_file)
        for url in ('file:///etc/passwd', 'http://upload.wikimedia.org/a.png', 'https://evil.example/a.png',
                    'https://user:password@upload.wikimedia.org/a.png', 'https://upload.wikimedia.org@evil.example/a.png'):
            with self.subTest(url=url):
                candidate = copy.deepcopy(self.catalog); candidate['items'][0]['source_url'] = url
                self.catalog_file.write_bytes(workflow.canonical(candidate))
                with self.assertRaises(ValueError): workflow.catalog_at(self.catalog_file)
        self.catalog_file.write_text('{"schema":"a","schema":"b"}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'duplicate'): workflow.catalog_at(self.catalog_file)

    def test_workspace_never_adopts_research_data_or_changed_catalog(self):
        research = self.root / 'research'; research.mkdir(); (research / 'graphics.sqlite').write_bytes(b'preserve')
        with self.assertRaisesRegex(ValueError, 'research'): workflow.ensure_workspace(research, self.catalog)
        self.assertEqual((research / 'graphics.sqlite').read_bytes(), b'preserve')
        unrelated = self.root / 'unrelated'; unrelated.mkdir(); (unrelated / 'notes.txt').write_text('preserve')
        with self.assertRaises(ValueError): workflow.ensure_workspace(unrelated, self.catalog)
        changed = copy.deepcopy(self.catalog); changed['items'][0]['rights']['attribution'] += ' changed'
        before = (self.workspace / 'workspace.json').read_bytes()
        with self.assertRaises(ValueError): workflow.ensure_workspace(self.workspace, changed)
        self.assertEqual((self.workspace / 'workspace.json').read_bytes(), before)

    def test_workspace_lock_excludes_another_writer_process(self):
        script = ("import sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);import workflow;"
                  "lock=workflow.workspace_lock(Path(sys.argv[2]));lock.__enter__()")
        with workflow.workspace_lock(self.workspace):
            result = subprocess.run([sys.executable, '-c', script, str(Path(workflow.__file__).parent), str(self.workspace)],
                                    capture_output=True, text=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('owns this workspace', result.stderr)
        with workflow.workspace_lock(self.workspace): pass

    def test_collect_checks_downloads_and_preserves_existing_source_bytes(self):
        for path in (self.workspace / 'sources').iterdir(): path.unlink()
        class Download(io.BytesIO):
            url = 'https://upload.wikimedia.org/synthetic-tests/pinned.png'
        def download(request, **_kwargs):
            return Download(self.images[request.full_url.rsplit('/', 1)[-1]])
        with patch('workflow.urllib.request.urlopen', side_effect=download):
            result = workflow.collect(self.workspace, self.catalog)
        self.assertEqual(result['status'], 'unreviewed')
        for item in self.catalog['items']: self.assertTrue(workflow.verified_source(self.workspace, item).is_file())
        source = self.workspace / 'sources' / self.catalog['items'][0]['source_filename']
        source.write_bytes(b'corrupt but must not be replaced implicitly')
        with patch('workflow.urllib.request.urlopen') as network:
            with self.assertRaisesRegex(ValueError, 'checksum'): workflow.collect(self.workspace, self.catalog)
            network.assert_not_called()
        self.assertEqual(source.read_bytes(), b'corrupt but must not be replaced implicitly')

    def test_bad_downloads_never_become_cached_sources(self):
        source = self.workspace / 'sources' / self.catalog['items'][0]['source_filename']; source.unlink()
        class Download(io.BytesIO):
            url = 'https://upload.wikimedia.org/synthetic-tests/pinned.png'
        with patch('workflow.urllib.request.urlopen', return_value=Download(b'wrong bytes')):
            with self.assertRaises(ValueError): workflow.collect(self.workspace, self.catalog)
        self.assertFalse(source.exists())
        self.assertEqual(list(source.parent.glob('.download-*')), [])


class AnnotationTrust(Fixture):
    def test_blind_reads_expose_only_requested_review_and_keep_prior_revisions(self):
        first = self.store.save(self.payload())
        path = self.store.directory(self.readers[0], self.item) / '00000001.json'
        original = path.read_bytes()
        self.assertEqual(self.store.latest(self.readers[1], self.item), {'revision': 0, 'regions': [], 'complete': False})
        self.assertEqual(self.store.latest(self.readers[0].swapcase(), self.item)['regions'], first['regions'])
        with self.assertRaises(workflow.RevisionConflict): self.store.save(self.payload())
        self.assertEqual(path.read_bytes(), original)
        second = self.store.save(self.payload(expected_revision=1))
        self.assertEqual(second['revision'], 2)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(len(list(path.parent.glob('*.json'))), 2)

    def test_completion_requires_explicit_visual_attestation_and_readable_text(self):
        for changes in ({'human_reviewed': False}, {'human_reviewed': 1}, {'complete': 'yes'}, {'protocol': 'short'}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError): self.store.save(self.payload(**changes))
        empty = self.payload(); empty['regions'][0]['text'] = ''; empty['regions'][0]['protected_terms'] = []
        with self.assertRaises(ValueError): self.store.save(empty)
        empty['regions'][0]['recognition_evaluable'] = False
        saved = self.store.save(empty)
        self.assertFalse(saved['regions'][0]['recognition_evaluable'])

    def test_comparison_and_adjudication_require_three_distinct_reviewers(self):
        self.store.save(self.payload())
        with self.assertRaises(ValueError): self.store.comparison(self.item, self.readers[0], self.readers[1])
        with self.assertRaises(ValueError): self.store.comparison(self.item, self.readers[0], ' SYNTHETIC  READER A ')
        self.store.save(self.payload(self.readers[1]))
        compared = self.store.comparison(self.item, *self.readers)
        self.assertEqual(len(compared['pairs']), 1)
        with self.assertRaisesRegex(ValueError, 'third reviewer'):
            self.store.save(self.payload(adjudication={'reviewers': self.readers, 'rationale': 'A synthetic explanation longer than thirty-two characters.'}, expected_revision=1))
        with self.assertRaises(ValueError): self.freeze(adjudicator=self.readers[0])

    def test_incomplete_stale_and_short_adjudications_cannot_freeze(self):
        self.independent()
        decision = {'reviewers': self.readers, 'rationale': 'Synthetic adjudication rationale longer than thirty-two characters.'}
        with self.assertRaises(ValueError): self.store.save(self.payload(self.adjudicator, adjudication={**decision, 'rationale': 'short'}))
        short = self.payload(self.adjudicator, adjudication=decision); short['regions'][0]['rationale'] = 'short'
        with self.assertRaises(ValueError): self.store.save(short)
        self.store.save(self.payload(self.adjudicator, adjudication=decision, complete=False))
        with self.assertRaisesRegex(ValueError, 'incomplete'): self.freeze()
        self.store.save(self.payload(self.adjudicator, adjudication=decision, expected_revision=1))
        self.store.save(self.payload(expected_revision=1))
        with self.assertRaisesRegex(ValueError, 'changed after adjudication'): self.freeze()
        self.assertFalse((self.root / 'synthetic-gold.json').exists())

    def test_freeze_preserves_literal_content_and_annotation_digest_provenance(self):
        self.adjudicated()
        output = self.root / 'synthetic-gold.json'
        result = self.freeze(output)
        gold = workflow.load(output)
        self.assertEqual(result['sha256'], workflow.file_digest(output))
        self.assertEqual(gold['split'], 'held_out')
        self.assertEqual(len(gold['items']), 1)
        self.assertEqual(gold['items'][0]['regions'][0]['text'], 'Ö 8′')
        self.assertIn('self-attested', gold['workflow']['identity_limit'])
        provenance = gold['workflow']['provenance'][0]['annotations']
        self.assertEqual(len(provenance), 3)
        for record in provenance:
            path = self.store.directory(record['reviewer'], self.item) / f"{record['revision']:08d}.json"
            self.assertEqual(record['sha256'], workflow.file_digest(path))
        original = output.read_bytes()
        with self.assertRaises(ValueError): self.freeze(output)
        self.assertEqual(output.read_bytes(), original)

    def test_incomplete_adjudication_draft_can_save_without_becoming_frozen_gold(self):
        self.independent()
        draft = self.store.save(self.payload(self.adjudicator, complete=False, adjudication={
            'reviewers': self.readers, 'rationale': ''}))
        self.assertFalse(draft['complete'])
        with self.assertRaisesRegex(ValueError, 'incomplete'): self.freeze()
        self.assertFalse((self.root / 'synthetic-gold.json').exists())

    def test_freeze_cannot_publish_into_sources_or_annotation_history(self):
        self.adjudicated()
        for name in ('sources', 'annotations'):
            output = self.workspace / name / 'forbidden-gold.json'
            with self.subTest(directory=name):
                with self.assertRaises(ValueError): self.freeze(output)
                self.assertFalse(output.exists())

    def test_competing_freezes_never_replace_the_winner_or_leave_partial_manifests(self):
        self.adjudicated()
        output = self.root / 'synthetic-gold.json'
        original_publish = workflow.publish_new
        barrier = threading.Barrier(2)
        def simultaneous_publish(path, content):
            if path == output: barrier.wait(timeout=5)
            return original_publish(path, content)
        def freeze_once():
            try: return self.freeze(output)
            except FileExistsError: return None
        with patch('workflow.publish_new', side_effect=simultaneous_publish):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: freeze_once(), range(2)))
        winners = [result for result in results if result is not None]
        self.assertEqual(len(winners), 1)
        self.assertEqual(workflow.file_digest(output), winners[0]['sha256'])
        workflow.score.validate_gold(workflow.load(output))
        self.assertEqual(list(output.parent.glob('.pending-*')), [])

    def test_source_corruption_blocks_freeze_and_annotation_service(self):
        self.adjudicated()
        path = self.workspace / 'sources' / self.catalog['items'][0]['source_filename']
        path.write_bytes(path.read_bytes() + b'changed')
        with self.assertRaisesRegex(ValueError, 'checksum'): self.freeze()
        with self.assertRaisesRegex(ValueError, 'checksum'): workflow.make_server(self.workspace, self.catalog, 0)
        self.assertFalse((self.root / 'synthetic-gold.json').exists())


class AnnotationHTTP(Fixture):
    def setUp(self):
        super().setUp()
        self.server = workflow.make_server(self.workspace, self.catalog, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=5)

    def request(self, path, method='GET', data=None, headers=None):
        body = workflow.canonical(data) if isinstance(data, dict) else data
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=5)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse(); content = response.read()
            try: value = json.loads(content)
            except (ValueError, UnicodeDecodeError): value = content
            return response.status, value, dict(response.getheaders())
        finally:
            connection.close()

    @staticmethod
    def annotation_query(item, reviewer):
        return '/api/annotation?' + urllib.parse.urlencode({'item': item, 'reviewer': reviewer})

    def test_blind_http_catalog_and_own_revision_without_other_readers_text(self):
        self.store.save(self.payload())
        code, catalog, headers = self.request('/api/catalog')
        self.assertEqual(code, 200); self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertNotIn('regions', catalog['items'][0]); self.assertNotIn('candidates', catalog['items'][0])
        code, blind, _ = self.request(self.annotation_query(self.item, self.readers[1]))
        self.assertEqual(code, 200); self.assertEqual(blind['regions'], []); self.assertNotIn('reviewer', blind)
        code, own, _ = self.request(self.annotation_query(self.item, self.readers[0]))
        self.assertEqual(code, 200); self.assertEqual(own['regions'][0]['text'], 'Ö 8′')
        code, _, _ = self.request('/api/compare?' + urllib.parse.urlencode({'item': self.item, 'reviewer_a': self.readers[0], 'reviewer_b': self.readers[1]}))
        self.assertEqual(code, 422)

    def test_post_revision_conflict_is_409_and_preserves_previous_files(self):
        headers = {'Content-Type': 'application/json', 'X-Scriptor-Annotation': '1'}
        code, saved, _ = self.request('/api/annotation', 'POST', self.payload(), headers)
        self.assertEqual(code, 200); self.assertEqual(saved['revision'], 1)
        files = {str(path): path.read_bytes() for path in (self.workspace / 'annotations').rglob('*.json')}
        code, _, _ = self.request('/api/annotation', 'POST', self.payload(), headers)
        self.assertEqual(code, 409)
        self.assertEqual({str(path): path.read_bytes() for path in (self.workspace / 'annotations').rglob('*.json')}, files)

    def test_concurrent_http_submissions_publish_exactly_one_revision(self):
        headers = {'Content-Type': 'application/json', 'X-Scriptor-Annotation': '1'}
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(lambda _: self.request('/api/annotation', 'POST', self.payload(), headers)[0], range(2)))
        self.assertEqual(sorted(statuses), [200, 409])
        self.assertEqual(self.store.latest(self.readers[0], self.item)['revision'], 1)
        self.assertEqual(len(list((self.workspace / 'annotations').rglob('*.json'))), 1)

    def test_origin_custom_header_json_and_path_guards_cannot_write_annotations(self):
        allowed = {'Content-Type': 'application/json', 'X-Scriptor-Annotation': '1'}
        cases = [({}, 403), ({'Content-Type': 'application/json'}, 403),
                 ({**allowed, 'Origin': 'https://untrusted.example'}, 403),
                 ({**allowed, 'Content-Type': 'text/plain'}, 403)]
        for headers, expected in cases:
            with self.subTest(headers=headers): self.assertEqual(self.request('/api/annotation', 'POST', self.payload(), headers)[0], expected)
        self.assertEqual(self.request('/api/annotation', 'POST', b'{"reviewer":"a","reviewer":"b"}', allowed)[0], 422)
        for path in ('/../workspace.json', '/%2e%2e/workspace.json', '/annotations/private.json', '/image/../workspace.json'):
            with self.subTest(path=path): self.assertIn(self.request(path)[0], (404, 422))
        self.assertEqual(self.request('/../workspace.json', 'POST', self.payload(), allowed)[0], 404)
        self.assertEqual(list((self.workspace / 'annotations').rglob('*.json')), [])

    def test_image_preview_rechecks_source_integrity(self):
        code, body, headers = self.request('/image/' + self.item)
        self.assertEqual(code, 200); self.assertTrue(body.startswith(b'\x89PNG'))
        self.assertEqual(headers['Content-Type'], 'image/png')
        source = self.workspace / 'sources' / self.catalog['items'][0]['source_filename']
        source.write_bytes(b'changed')
        self.assertEqual(self.request('/image/' + self.item)[0], 422)


if __name__ == '__main__':
    unittest.main(verbosity=2)
