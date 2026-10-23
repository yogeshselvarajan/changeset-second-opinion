/**
 * Every sentence on the public pages, in one file. The workspace settings override the
 * name, the tagline and the community paragraph from the API; this file is the fallback and what
 * the build uses when the API cannot be reached. No dashes, no exclamation marks, and none of the
 * words the product never uses (the banned-words check in CI covers this file).
 *
 * Voice: a calm person who has done this job, talking to someone who does it. The home page sells
 * the outcome and keeps engineering words out; the About page is where the working parts, the
 * figures and every caveat live.
 */

declare const __CSO_REPO_URL__: string;

export const REPO_URL: string =
  typeof __CSO_REPO_URL__ === "string"
    ? __CSO_REPO_URL__
    : "https://github.com/yogeshselvarajan/changeset-second-opinion";

export const copy = {
  name: "Changeset Second Opinion",
  shortName: "Second Opinion",
  tagline: "Evidence first; a human posts.",
  headline: "Every flagged edit deserves a second opinion.",
  /** The closing words of the headline, drawn in the accent colour. Must end the headline. */
  headlineEmphasis: "second opinion.",
  description: "A second opinion on flagged OpenStreetMap edits. Evidence first; a human posts.",

  nav: {
    how: "How it works",
    receipts: "Receipts",
    communities: "Communities",
    openSource: "Open source",
    about: "About",
    docs: "Docs",
    github: "GitHub",
    open: "Open the queue",
    openShort: "Queue",
    label: "Site",
    menu: "Menu",
  },
  hero: {
    badge: "Free and open source",
    badgeNote: "Made for OpenStreetMap volunteers",
    sub: "Changeset Second Opinion lays out the evidence, shows every answer and drafts the kind reply, so the people who look after the map can do it without burning out. You decide. You post.",
    primary: "Open the queue",
    secondary: "See how it works",
    note: "Reads the map. Never changes it.",
  },
  reads: {
    label: "What it reads for every flagged edit",
    items: [
      "The account and its age",
      "The edit comment",
      "Features that were deleted",
      "Every tag that changed",
      "Where and how big",
      "The discussion",
      "The editor used",
      "What could not be fetched",
    ],
  },
  basics: {
    eyebrow: "New here?",
    title: "The map belongs to everyone. So does looking after it.",
    items: [
      {
        title: "OpenStreetMap",
        body: "A free map of the world, drawn by volunteers and used by apps, delivery services and emergency teams. Anyone can add a road, fix a name or draw a building.",
        link: "What is OpenStreetMap",
        href: "https://www.openstreetmap.org/about",
      },
      {
        title: "A changeset",
        body: "Each time a mapper saves their work, OpenStreetMap keeps one changeset: a bundle of edits with a comment, a time and an author. It is the unit a reviewer looks at.",
        link: "About changesets",
        href: "https://wiki.openstreetmap.org/wiki/Changeset",
      },
      {
        title: "A flagged edit",
        body: "Tools such as OSMCha and MapRoulette flag changesets that look unusual. Most are honest mistakes by new mappers. Someone still has to check, and that is where this tool helps.",
        link: "See OSMCha",
        href: "https://osmcha.org",
      },
    ],
  },
  problem: {
    eyebrow: "The problem",
    title: "Flaggers hand you a queue. They do not hand you understanding.",
    body: [
      "Every day, volunteers open edits that something has flagged. Most are honest mistakes. A few need real attention. Telling them apart means five tabs, a pile of tag differences and a guess at what the mapper meant. Then comes the hard part: finding kind words for a stranger.",
      "That is a lot to ask of someone on a Tuesday night. So we built the second pair of eyes.",
    ],
  },
  how: {
    eyebrow: "How it works",
    title: "From flag to reply on one calm screen.",
    items: [
      {
        title: "See the whole story",
        body: "The comment, the account, the place, the counts and every tag that changed, on one page, with a plain list of anything we could not fetch.",
      },
      {
        title: "Ten honest questions",
        body: "Was something old deleted? Is the account brand new? Each answer is shown with how sure the tool was. When it cannot tell, it says so, and that never raises the alarm.",
      },
      {
        title: "You write, you post",
        body: "A friendly draft is ready to edit and copy. The tool can read the map and can never change it, so posting is always your move.",
      },
    ],
  },
  strip: {
    eyebrow: "Show your working",
    title: "Every answer sits next to what it was shown.",
    caption: "Nothing is a black box: the evidence and the reading appear side by side.",
    label: "Example tag changes",
  },
  receipt: {
    eyebrow: "Receipts",
    title: "A receipt for every verdict.",
    body: "Share a link and anyone can see the facts, the rules that fired, how much of the edit the evidence covered and which settings were in force. No names, no drafts, no guesswork.",
    disclosure:
      "An example receipt built from invented data, so the readings are illustrative and not a live decision.",
    id: "900000000002",
  },
  promises: {
    eyebrow: "Our promises",
    title: "Three things it will not do.",
    items: [
      {
        title: "It never edits the map",
        body: "It can only read. The rule is enforced in code, and the build fails if that ever changes.",
      },
      {
        title: "It never hides a case",
        body: "Cases are put in order, never buried. Every queue is visible and counted, and nothing closes by itself.",
      },
      {
        title: "It never decides for you",
        body: "A suggestion is a suggestion. Nothing is flagged, closed or posted unless a person does it.",
      },
    ],
  },
  communities: {
    eyebrow: "For communities",
    title: "Tuned to how your community works.",
    body: "Every community looks after the map in its own way. Pick a pack that fits yours, such as a warmer welcome for newcomers or closer scrutiny, and adjust it from your own reviewers' decisions. Nothing changes unless an admin applies it.",
    link: "How packs work",
    packsLabel: "Choose a pack",
    packs: [
      {
        id: "default",
        title: "Default",
        body: "The balanced starting point. A good place to begin and to compare against.",
      },
      {
        id: "newcomer-friendly",
        title: "Newcomer friendly",
        body: "For communities that mostly meet new mappers. A new account gets a welcome before a question, and a beginner guide may be linked in a draft.",
      },
      {
        id: "strict-review",
        title: "Strict review",
        body: "For communities that want closer scrutiny. Older features count sooner, and the tool asks for fewer unknown readings.",
      },
    ],
    signIn: "Sign in with OpenStreetMap, read-only scope.",
    inviteOnly: "Invite-only while in review.",
  },
  engine: {
    eyebrow: "How it thinks",
    title: "Two models, each with one small job.",
    body: "A small open model answers the questions. A writing model only helps when you ask for a comment. Neither one decides anything for you, and both are named here so you can look them up.",
    items: [
      {
        name: "Strands Decider 2B",
        role: "Answers ten yes or no questions",
        body: "A compact open model that reads the evidence for one changeset and answers each question with a probability for yes, no and cannot tell. It runs on its own, and every probability is shown to the reviewer.",
        links: [
          {
            label: "Model on Hugging Face",
            href: "https://huggingface.co/StrandsAgents/strands-decider-2B-qwen3.5-v1-2610",
          },
          { label: "Source code", href: "https://github.com/strands-labs/strands-decider" },
        ],
      },
      {
        name: "Claude Haiku 4.5 on Amazon Bedrock",
        role: "Drafts a comment, only when asked",
        body: "Writes a short, kind first comment from the evidence you already see. You edit it and post it yourself. The tool never posts for you.",
        links: [
          { label: "Amazon Bedrock", href: "https://aws.amazon.com/bedrock/" },
          { label: "Claude Haiku", href: "https://www.anthropic.com/claude/haiku" },
        ],
      },
      {
        name: "Strands Agents",
        role: "Keeps the drafting step tidy",
        body: "An open source toolkit for building agents. It runs the drafting step and keeps it to one clear tool.",
        links: [
          { label: "Strands Agents", href: "https://strandsagents.com" },
          { label: "On GitHub", href: "https://github.com/strands-agents/sdk-python" },
        ],
      },
    ],
  },
  decider: {
    eyebrow: "The decision model",
    title: "A small model that gives a reading, not a paragraph.",
    body: "Most AI tools hand a reviewer a wall of prose and ask for trust. The Strands Decider 2B does a different job. It reads the evidence for one changeset and answers ten fixed yes or no questions, each with a probability. A reading is a number you can compare, sort and challenge, and no language model is asked to guess what the edit meant.",
    inLabel: "Evidence in",
    inItems: [
      "The edit comment",
      "The account and its age",
      "Features that were deleted",
      "Every tag that changed",
      "The discussion",
    ],
    centerName: "Strands Decider 2B",
    centerNote: "{ms} ms of model time",
    outLabel: "Ten readings out",
    outNote: "Five of the ten, from a real run on changeset {id}, 20 October 2026.",
    yes: "yes",
    impactTitle: "Why it helps a reviewer",
    impact: [
      {
        title: "The same shape every time",
        body: "Every case gets the same ten questions, so two cases can be compared side by side and a pipeline can act on the answer.",
      },
      {
        title: "Quick and light",
        body: "Median {ms} ms of model time per changeset on one small GPU, measured on the {cases} demo cases. It also runs on a CPU, with no cloud bill per case.",
      },
      {
        title: "Open about doubt",
        body: "{unknown} of {readings} readings in the demo set came back as cannot tell. That is the model saying so. It never raises the alarm.",
      },
    ],
    why: "A general chat model can write a convincing paragraph about any edit, including a wrong one. The Decider is tuned for decisions like these, shows every probability and has no way to write to anything. The writing model comes in later, and only when you ask.",
  },
  story: {
    scenes: [
      { tag: "01", title: "Read", body: "The evidence gathers in one column beside the map." },
      { tag: "02", title: "Ask", body: "Ten questions, each ring filled to its probability." },
      { tag: "03", title: "Write", body: "A kind draft appears. You edit it and you post it." },
    ],
    footnote:
      "An illustration on invented streets. The ten readings are copied from a real run on changeset {id}.",
  },
  path: {
    eyebrow: "The path of one edit",
    title: "From a flagged changeset to your reply.",
    steps: [
      { name: "Read", body: "Public evidence is fetched, read only." },
      { name: "Decider 2B", body: "Ten readings, each with a probability." },
      { name: "Rules", body: "Counts, ages and coverage set the lane." },
      { name: "You decide", body: "Lanes only change the order. Nothing is hidden." },
      { name: "Haiku 4.5", body: "Drafts a kind comment, only when asked, on Amazon Bedrock." },
      { name: "You post", body: "You edit it and post it yourself." },
    ],
  },
  modes: {
    eyebrow: "Two ways to use it",
    title: "In the browser or on the command line.",
    body: "Reviewers use the web app. Whoever runs a workspace for a community can also use the command line. Both read the same data.",
    items: [
      {
        name: "The web app",
        who: "For reviewers",
        points: [
          "Browse the queue without signing in",
          "Sign in with OpenStreetMap (read only) or an invite code",
          "Ask for a draft, edit it and record what you decided",
        ],
      },
      {
        name: "Workspaces and admins",
        who: "For whoever runs it for a community",
        points: [
          "You name the admin's OpenStreetMap user id once, in one server setting. Only that account can claim a new workspace, in one confirmed step",
          "Invite codes, packs, branding and an export, all in Settings",
          "After that, no command line is needed",
        ],
      },
      {
        name: "The command line",
        who: "For developers and operators",
        points: [
          "cso seed, api and worker run the whole stack locally",
          "cso record saves any changeset as a replayable case",
          "cso eval and cso calibrate measure and tune it",
        ],
      },
    ],
    terminal: [
      "$ uv run cso seed",
      "seeded 15 new and 0 existing cases (15 snapshots, 15 runs)",
      "$ uv run cso api",
      "Uvicorn running on http://127.0.0.1:8000",
    ].join("\n"),
    signIn: "Sign in",
    openQueue: "Open the queue",
    docs: "Read the run guide",
  },
  different: {
    eyebrow: "How it is different",
    title: "It does not replace your tools. It explains their output.",
    rows: [
      {
        other: "Flagging tools such as OSMCha and MapRoulette",
        theirs: "Tell you which changesets to look at.",
        ours: "Shows why one matters: ten readings, the rules that fired and how much evidence was fetched.",
      },
      {
        other: "General chat assistants",
        theirs: "Write fluent prose, with no promise it is right.",
        ours: "Gives structured readings first, a draft second, and a person edits and posts every reply.",
      },
      {
        other: "Dashboards and counters",
        theirs: "Show how many changesets there are.",
        ours: "Keeps a receipt for each verdict, so a decision can be shared and checked later.",
      },
    ],
  },
  maker: {
    eyebrow: "Who built it",
    title: "Made by Yogesh Selvarajan.",
    body: "One developer, built for the AWS Agent Experience Hackathon: Strands Decider. Say hello, send a suggestion, or tell us how your community reviews edits.",
    hackathon: "The hackathon page",
    linkedin: "LinkedIn",
    builder: "AWS Builder Center",
    email: "yogeshselvarajan@gmail.com",
    sponsor: "Sponsor the work on GitHub",
    links: {
      sponsor: "https://github.com/sponsors/yogeshselvarajan",
      hackathon:
        "https://builder.aws.com/build/hackathons/4f50957c-1d08-37ab-b11c-97516b9adeb4/agent-experience-hackathon-strands-decider?tab=about",
      linkedin: "https://www.linkedin.com/in/yogesh-selvarajan/",
      builder: "https://builder.aws.com/community/@yogeshs",
      email: "mailto:yogeshselvarajan@gmail.com",
    },
  },
  straight: {
    eyebrow: "Straight talk",
    title: "What it can do today, said plainly.",
    body: "We tested the tool on 60 edits. The answer key was written by an AI, not by people, so please read the results as a first look and not as proof. The full scorecard, with every caveat, is public.",
    link: "Read the scorecard",
  },
  openSource: {
    eyebrow: "Open source",
    title: "Built in the open, for everyone who looks after the map.",
    body: "Changeset Second Opinion is free software under the Apache-2.0 licence. Read the code, run it for your own community, suggest a change, or tell us what would help you most.",
    github: "View on GitHub",
    run: "Run it yourself",
    docs: "Read the docs",
    contribute: "How to contribute",
    points: [
      "Free to use, change and share",
      "Works on sample data in minutes",
      "Your community sets its own tone and cut points",
    ],
  },
  cta: {
    title: "Give the next flagged edit a second opinion.",
    primary: "Open the queue",
    secondary: "Sign in to review",
  },
  numbers: {
    glanceTitle: "What the demo set shows",
    glanceIntro:
      "Fifteen real changesets from India, Kenya, Germany and Mexico, each read by the Strands Decider 2B on 20 October 2026. These figures are counted from the saved runs, not typed by hand.",
    glance: {
      cases: {
        value: "{cases}",
        label: "real changesets, each with a place and the mapper's own words",
      },
      questions: {
        value: "{perCase}",
        label: "questions answered for every one, every probability shown",
      },
      speed: { value: "{seconds} s", label: "median model time per changeset on one small GPU" },
      unknown: {
        value: "{unknown} of {readings}",
        label: "readings came back as cannot tell, and none of those raised an alarm",
      },
      lanes: {
        value: "{lanes}",
        label: "lanes used, so the queue is ordered and nothing is hidden",
      },
      writes: { value: "0", label: "writes to OpenStreetMap, by design and checked in the build" },
    },
    title: "The scorecard",
    sixtyTitle: "The test on 60 edits",
    readTitle: "How to read it",
    can: "What we can say: it answers about as accurately as always guessing the commonest answer, it says cannot tell when it does not know, and it names the kind of edit a little more often than the plain rules do.",
    cannot:
      "What we cannot say yet: that it beats a person. The answer key was written by an AI, and the gap on naming the kind of edit is small. The next step is an answer key written by volunteers.",
    items: {
      decided: {
        label: "Yes or no answers the tool got right",
        note: "Share of its answers, when it gave one, that matched the answer key.",
      },
      baseline: {
        label: "The same score with no tool at all",
        note: "Always giving each question its most common answer.",
      },
      unknown: {
        label: "Answers of “cannot tell”",
        note: "The tool saying it is not sure. This is the cautious answer.",
      },
      nature: {
        label: "Naming the kind of edit",
        note: "Against the plain rules alone: {rules}.",
      },
    },
    caveat:
      "Read the second figure next to the first. Someone who never looked at an edit would score about the same on this set, so these numbers alone do not show that the tool adds anything.",
  },
  run: {
    title: "Run it yourself",
    intro: "Try it on sample data with no special hardware and no cloud account.",
    command: [
      "git clone {repo}.git",
      "cd changeset-second-opinion/backend",
      "uv sync --frozen",
      "uv run cso db upgrade",
      "uv run cso seed",
      "uv run cso api",
    ].join("\n"),
    note: "Then run npm ci and npm run dev in the web folder. The README has the full steps.",
    copy: "Copy",
    copied: "Copied",
    commandLabel: "Commands to run it locally",
  },
  footer: {
    licence: "Code under the Apache-2.0 licence.",
    data: "Data © OpenStreetMap contributors, ODbL.",
    usage: "Follows the OpenStreetMap usage policy: read-only requests with a named contact.",
    built: "Built for the AWS Agent Experience Hackathon: Strands Decider.",
    builtHref:
      "https://builder.aws.com/build/hackathons/4f50957c-1d08-37ab-b11c-97516b9adeb4/agent-experience-hackathon-strands-decider?tab=about",
    madeBy: "Made by Yogesh",
    madeByHref: "https://www.linkedin.com/in/yogesh-selvarajan/",
    sponsor: "Support the project",
    lessMotion: "Less motion",
    fullMotion: "Full motion",
    motionLabel: "Motion on this site",
    privacy: "Privacy",
    about: "About",
    docs: "Docs",
    github: "GitHub",
    label: "Footer",
    blurb: "A second opinion on flagged OpenStreetMap edits.",
  },
  about: {
    title: "About",
    description:
      "What Changeset Second Opinion is, what it never does, how well it works so far, who built it and what it cannot do yet.",
    sections: [
      {
        id: "what",
        title: "What it is",
        paragraphs: [
          "When a changeset is flagged, somebody has to look at it, usually with many more waiting. This tool does the tedious part and leaves the part that needs judgement.",
          "It collects the evidence for one changeset, asks a small decision model ten yes or no questions about it, shows every answer, suggests a lane, and drafts a comment a reviewer can edit.",
        ],
      },
      {
        id: "never",
        title: "What it never does",
        paragraphs: [
          "It never writes to OpenStreetMap. The HTTP client only knows how to read, and a check in the build fails if that changes. The one exception is the sign-in exchange with OpenStreetMap, which asks for read-only access to your user name.",
          "It never hides a case. Lanes put the queue in an order, and every lane is shown with its count. It never closes or posts anything by itself.",
          "Rules read parsed facts such as counts, ages and coverage. A model answer can make a lane more cautious and never less.",
        ],
      },
    ],
    afterScorecard: [
      {
        id: "cannot",
        title: "What it cannot do yet",
        paragraphs: [
          "The scorecard above was marked against an answer key written by an AI, with no person checking it. Please read it as a first look, not as proof.",
          "Our sample has no clear example of deliberate damage, so we cannot say whether the tool would catch one. A second set of edits was put aside for a fair final test, but it has been run once without answers, so it is no longer completely fresh. A reviewer who wants to help can check the answer key.",
        ],
      },
    ],
    who: {
      id: "who",
      title: "Who built it",
      paragraphs: [
        "Made by Yogesh Selvarajan, as one developer, for the AWS Agent Experience Hackathon: Strands Decider. AI coding assistants helped write the code, and a person set the scope and made every decision. You can reach Yogesh on LinkedIn, on AWS Builder Center or at yogeshselvarajan@gmail.com.",
        "If the tool helps your community, you can sponsor the work on GitHub.",
      ],
    },
    independenceTitle: "Independence",
    sourceLink: "Read the code and the decision records",
  },
  privacy: {
    title: "Privacy",
    description:
      "What Changeset Second Opinion stores, for how long, and what it does not do: no tracking, no advertising, no third party scripts.",
    sections: [
      {
        title: "What this site does not do",
        paragraphs: [
          "The public pages set no cookies, load no third party scripts and use no analytics. Their one request to this server asks for the site's name, colour and logo; it carries no cookie and nothing about you.",
        ],
      },
      {
        title: "What is stored",
        paragraphs: [
          "Public OpenStreetMap data about the changesets that reviewers look at: the changeset, its elements, and public facts about the account that made it.",
          "What a reviewer decides: the decision, any note and comment text they write, and the name they sign in with. An invite code reviewer chooses a display name; a reviewer who signs in with OpenStreetMap is stored by user id and display name. No OpenStreetMap token is kept.",
          "A signed-in session uses two cookies, one for the session and one to protect against forged requests. They are removed when you sign out.",
          "The web server keeps an access log for 14 days to spot errors and abuse: the time, the address of the visitor with its last part removed, the path without any query, the status and the size. It holds no cookie and no header.",
        ],
      },
      {
        title: "How long",
        paragraphs: [
          "Decisions are kept as a record and are not edited; a correction is a new entry. An admin can export the history. Ask the contact below to have your entries reviewed or removed.",
        ],
      },
      {
        title: "Contact",
        paragraphs: [
          "Questions about privacy go to the contact address in the repository's security policy.",
        ],
      },
    ],
  },
  notFound: {
    title: "Page not found",
    description: "That address does not lead anywhere on this site.",
    body: "The page may have moved. The home page and the queue are the two places to start.",
    home: "Go to the home page",
  },
} as const;

/** Fill `{name}` placeholders. */
export function fill(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (match, key: string) =>
    key in values ? String(values[key]) : match,
  );
}
