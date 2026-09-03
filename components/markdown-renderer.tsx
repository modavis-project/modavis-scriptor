"use client";

import ReactMarkdown from "react-markdown";
import rehypeRaw from "rehype-raw";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import remarkGfm from "remark-gfm";

const scholarlyMarkdownSchema = {
  ...defaultSchema,
  tagNames: Array.from(new Set([...(defaultSchema.tagNames ?? []), "sup", "sub", "mark"])),
};

export function MarkdownRenderer({ content, label }: { content: string; label: string }) {
  return (
    <article
      aria-label={label}
      className="min-w-0 rounded-xl border border-stone-200 bg-[#fffefa] px-5 py-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.8)]"
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeRaw, [rehypeSanitize, scholarlyMarkdownSchema]]}
        components={{
          h1: ({ children }) => (
            <h1 className="mb-4 mt-1 font-serif text-2xl font-semibold leading-tight text-foreground">
              {children}
            </h1>
          ),
          h2: ({ children }) => (
            <h2 className="mb-3 mt-6 border-b border-stone-200 pb-2 font-serif text-xl font-semibold leading-tight text-foreground first:mt-1">
              {children}
            </h2>
          ),
          h3: ({ children }) => (
            <h3 className="mb-2 mt-5 font-serif text-lg font-semibold leading-snug text-foreground">
              {children}
            </h3>
          ),
          h4: ({ children }) => (
            <h4 className="mb-2 mt-4 text-sm font-bold text-foreground">{children}</h4>
          ),
          p: ({ children }) => (
            <p className="my-3 font-serif text-[15px] leading-7 text-foreground">{children}</p>
          ),
          ul: ({ children }) => (
            <ul className="my-3 list-disc space-y-1.5 pl-6 font-serif text-[15px] leading-7">
              {children}
            </ul>
          ),
          ol: ({ children }) => (
            <ol className="my-3 list-decimal space-y-1.5 pl-6 font-serif text-[15px] leading-7">
              {children}
            </ol>
          ),
          li: ({ children }) => <li className="pl-1">{children}</li>,
          blockquote: ({ children }) => (
            <blockquote className="my-4 border-l-4 border-teal/40 bg-teal-soft/25 px-4 py-1 text-stone-700">
              {children}
            </blockquote>
          ),
          table: ({ children }) => (
            <div className="my-4 overflow-x-auto rounded-lg border border-stone-200">
              <table className="w-full border-collapse text-left text-xs">{children}</table>
            </div>
          ),
          thead: ({ children }) => <thead className="bg-teal text-white">{children}</thead>,
          th: ({ children }) => (
            <th className="border-r border-white/15 px-3 py-2 font-semibold last:border-r-0">
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td className="border-r border-t border-stone-200 px-3 py-2 align-top last:border-r-0">
              {children}
            </td>
          ),
          a: ({ children, href }) => (
            <a
              href={href}
              target="_blank"
              rel="noreferrer"
              className="font-medium text-teal underline decoration-teal/30 underline-offset-2 hover:decoration-teal"
            >
              {children}
            </a>
          ),
          code: ({ children }) => (
            <code className="rounded bg-stone-100 px-1.5 py-0.5 font-mono text-[0.88em] text-coral">
              {children}
            </code>
          ),
          pre: ({ children }) => (
            <pre className="my-4 overflow-x-auto rounded-lg bg-[#17211f] p-4 text-xs leading-6 text-stone-100">
              {children}
            </pre>
          ),
          hr: () => <hr className="my-6 border-stone-200" />,
          sup: ({ children }) => <sup className="text-[0.7em] leading-none">{children}</sup>,
          sub: ({ children }) => <sub className="text-[0.7em] leading-none">{children}</sub>,
        }}
      >
        {content}
      </ReactMarkdown>
    </article>
  );
}
