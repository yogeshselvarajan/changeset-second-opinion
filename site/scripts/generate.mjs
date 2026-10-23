// Writes the reference pages that are made from the code, so they cannot drift from it.
//
//   settings, command line, roles and permissions, community pack schema, receipt schema
//
// The facts come from `uv run python -m cso.tools.export_docs` in ../backend. The REST API pages are
// drawn by the starlight-openapi plugin straight from backend/openapi/v1.json. Output goes to
// src/content/docs/reference/ and is committed; CI regenerates it (check-generated.mjs) and fails
// if the committed pages no longer match the app.
import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const backend = resolve(here, "..", "..", "backend");
const out = resolve(here, "..", "src", "content", "docs", "reference");

function readFacts() {
  const text = execFileSync("uv", ["run", "python", "-m", "cso.tools.export_docs"], {
    cwd: backend,
    encoding: "utf8",
    env: { ...process.env, PYTHONUTF8: "1" },
    maxBuffer: 64 * 1024 * 1024,
  });
  return JSON.parse(text);
}

const cell = (value) =>
  String(value ?? "")
    .replace(/\r?\n/g, " ")
    .replace(/\|/g, "\\|")
    .trim();

function table(headers, rows) {
  const lines = [`| ${headers.join(" | ")} |`, `| ${headers.map(() => "---").join(" | ")} |`];
  for (const row of rows) lines.push(`| ${row.map(cell).join(" | ")} |`);
  return lines.join("\n");
}

const banner = (source) =>
  `:::note[Generated page]\nThis page is written by \`site/scripts/generate.mjs\` from ${source}. Do not edit it by hand; change the code and rebuild.\n:::\n`;

function page(title, description, body) {
  return `---\ntitle: ${title}\ndescription: ${description}\n---\n\n${body.trim()}\n`;
}

function write(name, content) {
  mkdirSync(out, { recursive: true });
  writeFileSync(join(out, name), content, { encoding: "utf8" });
}

// ------------------------------------------------------------------ settings

/** Variables read outside the Settings class, each checked against the code that reads it. */
const OTHER_VARIABLES = [
  ["CSO_AUTH_SESSION_HOURS", "number", "12", "How long a sign-in lasts, in hours."],
  ["CSO_AUTH_IDLE_MINUTES", "number", "120", "A sign-in ends after this many idle minutes."],
  [
    "CSO_COOKIE_SECURE",
    "one of auto, true, false",
    "auto",
    "Whether the session cookie is marked secure. auto marks it secure on https.",
  ],
  [
    "CSO_TRUST_PROXY",
    "yes or no",
    "false",
    "Trust the X-Forwarded-For header for the visitor's address. Turn it on only behind a proxy that overwrites the header. The Compose files and the bootstrap script set it for you.",
  ],
  [
    "CSO_LIVE_ANON_READ",
    "yes or no",
    "false",
    "Let someone who is not signed in read the queue in live mode. In replay mode reading is always open.",
  ],
  [
    "CSO_LIVE_BEDROCK",
    "1 to allow",
    "not set",
    "The second gate on real Amazon Bedrock calls. They happen only in live mode and only when this is 1. Otherwise drafts come from the offline drafter.",
  ],
  [
    "CSO_DRAFT_DAILY_CALLS",
    "whole number",
    "200",
    "Most Bedrock draft calls per day.",
  ],
  [
    "CSO_DRAFT_DAILY_TOKENS",
    "whole number",
    "200000",
    "Most Bedrock tokens per day.",
  ],
  [
    "CSO_COMMUNITY_CONFIG",
    "file path",
    "config/communities/default.yaml",
    "The community pack file to load at start.",
  ],
  [
    "CSO_FIXTURES_DIR",
    "folder path",
    "backend/fixtures/demo",
    "The saved changesets that replay mode serves. The Docker image sets it to /app/fixtures/demo.",
  ],
  [
    "CSO_EVAL_DIR",
    "folder path",
    "evaluation",
    "Where cso eval reads labels and writes results.",
  ],
];

function settingsPage(settings) {
  const core = settings.map((s) => [
    `\`${s.env}\``,
    s.type,
    s.secret ? "secret, never shown" : `\`${s.default}\``,
    s.description,
  ]);
  const other = OTHER_VARIABLES.map(([env, type, def, desc]) => [`\`${env}\``, type, def, desc]);
  return page(
    "Settings reference",
    "Every environment variable the backend reads, with its type, default and meaning.",
    `*For operators and contributors. Reference.*

${banner("the \`Settings\` class in \`backend/src/cso/settings.py\`")}
Set these in the environment, or in \`backend/.env\` (the \`.env\` file next to where you start the app). Names start with \`CSO_\`. A value that is not valid halts the app at start with a message that names the variable, so a typo never opens something up quietly.

## Main settings

${table(["Variable", "Type", "Default", "What it does"], core)}

## Other variables

These are read in other places in the code and are not part of the \`Settings\` class.

${table(["Variable", "Type", "Default", "What it does"], other)}

## Related pages

- [Register the OpenStreetMap sign-in app](../../self-host/register-the-osm-app/)
- [Set up the first admin](../../administer/first-admin/)
- [Replay mode and live mode](../../self-host/replay-and-live/)
`,
  );
}

// ------------------------------------------------------------------ command line

function argumentRows(args) {
  return args.map((a) => {
    const name = a.flags.length ? a.flags.join(", ") : a.name;
    const details = [];
    if (a.choices.length) details.push(`one of ${a.choices.join(", ")}`);
    if (a.default !== null) details.push(`default ${a.default}`);
    if (a.flags.length && a.required) details.push("required");
    return [`\`${name}\``, a.help || "", details.join("; ")];
  });
}

function cliPage(commands) {
  const top = commands.filter((c) => c.command.split(" ").length === 2);
  const sections = commands
    .filter((c) => c.arguments.length > 0 || c.subcommands.length === 0)
    .map((c) => {
      const depth = c.command.split(" ").length;
      const heading = "#".repeat(Math.min(depth + 1, 4));
      const rows = argumentRows(c.arguments);
      return `${heading} \`${c.command}\`\n\n${c.description || ""}\n\n${
        rows.length ? table(["Argument", "What it does", "Details"], rows) : "No arguments."
      }\n`;
    })
    .join("\n");
  const index = table(
    ["Command", "What it does"],
    top.map((c) => [`\`${c.command}\``, c.description || ""]),
  );
  return page(
    "Command line reference",
    "Every cso command and its arguments.",
    `*For operators and contributors. Reference.*

${banner("the argument parser in \`backend/src/cso/cli.py\`")}
The \`cso\` command is installed with the backend. Run it from the \`backend\` folder with \`uv run cso <command>\`. Add \`--help\` to any command to see the same text in your terminal.

## Commands

${index}

## Arguments

${sections}
`,
  );
}

// ------------------------------------------------------------------ roles

const ROLE_TEXT = [
  [
    "no sign-in",
    "Anyone, including the public receipt links and the sign-in redirects.",
  ],
  [
    "viewer",
    "Someone browsing without signing in (replay mode), or any signed-in person. Can read the queue, cases, evidence, runs, config and history. Cannot change anything.",
  ],
  [
    "reviewer",
    "Signed in with OpenStreetMap or an invite code. Can add and analyse changesets, ask for drafts and record outcomes.",
  ],
  [
    "admin",
    "Can also see invites, versions, reliability and the decisions export, change settings, activate a community pack, calibrate and manage invites.",
  ],
];

function rolesPage(roles) {
  const rows = roles.map((r) => [r.method, `\`${r.path}\``, r.role, r.summary]);
  return page(
    "Roles and permissions",
    "The lowest role that can call each endpoint.",
    `*For admins and operators. Reference.*

${banner("the endpoint inventory in \`backend/src/cso/api/inventory.py\`, which a contract test keeps equal to the running app")}
Roles are ordered: viewer, then reviewer, then admin. A higher role can do everything a lower one can.

## The roles

${table(["Role", "Who and what"], ROLE_TEXT)}

In live mode, reading needs a sign-in unless the operator sets \`CSO_LIVE_ANON_READ\`. See [Settings reference](../settings/).

## Every endpoint

${table(["Method", "Path", "Lowest role", "What it does"], rows)}
`,
  );
}

// ------------------------------------------------------------------ schemas

function refName(ref) {
  return ref.split("/").pop();
}

function typeOf(prop) {
  if (!prop) return "";
  if (prop.$ref) return refName(prop.$ref);
  if (prop.const !== undefined) return `\`${prop.const}\``;
  if (prop.enum) return `one of ${prop.enum.join(", ")}`;
  if (prop.anyOf) {
    const parts = prop.anyOf.map(typeOf).filter((t) => t && t !== "null");
    const nullable = prop.anyOf.some((p) => p.type === "null");
    return parts.join(" or ") + (nullable ? ", optional" : "");
  }
  if (prop.type === "array") return `list of ${typeOf(prop.items) || "values"}`;
  if (prop.type === "object") {
    return prop.additionalProperties ? `map of ${typeOf(prop.additionalProperties)}` : "object";
  }
  if (prop.type === "integer") return "whole number";
  if (prop.type === "number") return "number";
  if (prop.type === "boolean") return "yes or no";
  if (prop.type === "string") return "text";
  return prop.type ?? "";
}

function describeDef(name, def) {
  const props = def.properties ?? {};
  const required = new Set(def.required ?? []);
  const rows = Object.entries(props).map(([key, prop]) => [
    `\`${key}\``,
    typeOf(prop),
    required.has(key) ? "yes" : "no",
    prop.default === undefined ? "" : `\`${JSON.stringify(prop.default)}\``,
    prop.description ?? prop.title ?? "",
  ]);
  const intro = def.description ? `${def.description}\n\n` : "";
  if (!rows.length) return `### ${name}\n\n${intro}${def.enum ? `One of ${def.enum.join(", ")}.` : ""}\n`;
  return `### ${name}\n\n${intro}${table(["Field", "Type", "Required", "Default", "Meaning"], rows)}\n`;
}

function schemaPage(title, description, audience, source, schema, rootName) {
  const defs = schema.$defs ?? {};
  const sections = [describeDef(rootName, schema)];
  for (const [name, def] of Object.entries(defs)) sections.push(describeDef(name, def));
  return page(
    title,
    description,
    `*${audience}. Reference.*

${banner(source)}
${sections.join("\n")}
`,
  );
}

// ------------------------------------------------------------------ run

const facts = readFacts();
write("settings.md", settingsPage(facts.settings));
write("command-line.md", cliPage(facts.cli));
write("roles-and-permissions.md", rolesPage(facts.roles));
write(
  "community-pack-schema.md",
  schemaPage(
    "Community pack schema",
    "The fields of a community pack file, with types and defaults.",
    "For admins and contributors",
    "the `CommunityConfig` model in `backend/src/cso/domain/config.py`",
    facts.schemas.community_pack,
    "CommunityConfig",
  ),
);
write(
  "receipt-schema.md",
  schemaPage(
    "Receipt schema",
    "The fields of a decision receipt, with types and defaults.",
    "For operators and contributors",
    "the `DecisionReceipt` model in `backend/src/cso/domain/receipt.py`",
    facts.schemas.receipt,
    "DecisionReceipt",
  ),
);
console.log(
  `generated 5 reference pages (${facts.settings.length} settings, ${facts.cli.length} commands, ${facts.roles.length} endpoints)`,
);
