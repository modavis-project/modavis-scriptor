// Select a real Python interpreter without assuming a Windows python3 alias.
import { spawn, spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const managed = path.join(root, "services/graphics/.venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
const candidates = process.env.SCRIPTOR_PYTHON
  ? [[process.env.SCRIPTOR_PYTHON]]
  : [
      ...(existsSync(managed) ? [[managed]] : []),
      ...(process.platform === "win32" ? [["python"], ["py", "-3.12"], ["python3"]] : [["python3"], ["python"]]),
    ];
const selected = candidates.find(([program, ...prefix]) => {
  const check = spawnSync(program, [...prefix, "-c", "import sys; sys.exit(sys.version_info < (3,9))"], {
    stdio: "ignore", timeout: 5000, windowsHide: true,
  });
  return check.status === 0;
});
if (!selected) {
  console.error("Python 3.9+ is required for host tools; set SCRIPTOR_PYTHON to its executable. Native graphics uses Python 3.12.");
  process.exit(1);
}
const [program, ...prefix] = selected;
const child = spawn(program, [...prefix, ...process.argv.slice(2)], {
  stdio: "inherit", windowsHide: true, env: { ...process.env, PYTHONUTF8: process.env.PYTHONUTF8 ?? "1" },
});
for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => child.kill(signal));
child.on("error", (error) => { console.error(error.message); process.exitCode = 1; });
child.on("exit", (code, signal) => { process.exitCode = code ?? (signal === "SIGINT" ? 130 : signal === "SIGTERM" ? 143 : 1); });
