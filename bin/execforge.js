#!/usr/bin/env node

const fs = require("node:fs");
const { spawnSync } = require("node:child_process");
const path = require("node:path");

const args = process.argv.slice(2);
const packageRoot = path.resolve(__dirname, "..");
const packageJsonPath = path.join(packageRoot, "package.json");
const srcPath = path.join(packageRoot, "src");
const hasLocalSrc = fs.existsSync(srcPath);

const env = { ...process.env };
if (hasLocalSrc) {
  const pathSep = process.platform === "win32" ? ";" : ":";
  env.PYTHONPATH = env.PYTHONPATH ? `${srcPath}${pathSep}${env.PYTHONPATH}` : srcPath;
}

const packageJson = JSON.parse(fs.readFileSync(packageJsonPath, "utf8"));
const packageVersion = packageJson.version;

const attempts =
  process.platform === "win32"
    ? [
        ["py", ["-3", "-m", "orchestrator.cli.main", ...args]],
        ["python", ["-m", "orchestrator.cli.main", ...args]],
      ]
    : [
        ["python3", ["-m", "orchestrator.cli.main", ...args]],
        ["python", ["-m", "orchestrator.cli.main", ...args]],
      ];

for (const [command, commandArgs] of attempts) {
  const probe = spawnSync(
    command,
    ["-c", "import orchestrator, typer, sqlalchemy, yaml, platformdirs, rich"],
    {
      env,
      encoding: "utf8",
    }
  );
  if (probe.error) {
    if (probe.error.code !== "ENOENT") {
      console.error(`Failed to launch '${command}': ${probe.error.message}`);
      process.exit(1);
    }
    continue;
  }

  if (probe.status !== 0) {
    const install = spawnSync(
      command,
      ["-m", "pip", "install", "--user", `execforge==${packageVersion}`],
      {
        env,
        stdio: "inherit",
      }
    );
    if (install.status !== 0) {
      process.exit(install.status ?? 1);
    }
  }

  const result = spawnSync(command, commandArgs, {
    env,
    stdio: "inherit",
  });
  if (result.error) {
    console.error(`Failed to launch '${command}': ${result.error.message}`);
    process.exit(1);
  }
  process.exit(result.status ?? 1);
}

console.error(
  "Execforge requires Python 3.11+ on PATH. Install Python, then retry this command."
);
process.exit(1);
