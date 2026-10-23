import type { PublicReceipt } from "../api/types.gen";

/**
 * The receipt shown on the home page: synthetic case 02 (a new mapper renames a residential road
 * to a shop name). The case, its coverage, its lane and its nature come from
 * `backend/fixtures/cases/02-good-faith-mistake/expected.json`; the fixture stores no model
 * readings, so the probabilities below are illustrative and the page says so. Nothing here is a
 * live decision and no real account or changeset is named.
 */
export const SAMPLE_RECEIPT: PublicReceipt = {
  run_id: "00000000-0000-4000-8000-000000000002",
  changeset_id: 900000000002,
  created_at: "2026-10-17T09:00:00Z",
  config_version: "sha256:01ae6fdd985091161326815b8c3f73b8f3f00c285fe77db6d1987512fc60656e",
  pack_id: "default",
  calibration_version: null,
  decider: { model: "strands-decider-2B", checkpoint: "qwen3.5-v1-2610" },
  lane: "review_suggested",
  band: "unsure",
  nature: "likely_good_faith_mistake",
  response: "welcome_and_tips",
  probes: [
    {
      code: "new_account_first_edits",
      label: "The account is new or has very few changesets",
      probability: 0.93,
      reading: "yes",
    },
    {
      code: "mature_feature_deleted",
      label: "An old or heavily edited feature was deleted",
      probability: 0.05,
      reading: "no",
    },
    {
      code: "nonsense_or_offensive_values",
      label: "New tag values look like nonsense, a test string or a name",
      probability: 0.12,
      reading: "no",
    },
    {
      code: "comment_matches_changes",
      label: "The changeset comment matches the edits",
      probability: 0.41,
      reading: "unknown",
    },
    {
      code: "conventions_followed",
      label: "New or changed tags follow ordinary OSM conventions",
      probability: 0.38,
      reading: "unknown",
    },
    {
      code: "real_world_change_claimed",
      label: "The edits claim a real-world change that tags cannot confirm",
      probability: 0.57,
      reading: "unknown",
    },
    {
      code: "discussion_cites_source",
      label: "The discussion names a survey, imagery or other source",
      probability: 0.04,
      reading: "no",
    },
    {
      code: "mass_retag_single_key",
      label: "One tag key was changed on more than 20 elements",
      probability: 0.03,
      reading: "no",
    },
    {
      code: "evidence_sufficient",
      label: "The evidence covers all deletions and most modified elements",
      probability: 0.9,
      reading: "yes",
    },
  ],
  rules_fired: [],
  coverage: {
    score: 1,
    elements_in_changeset: 2,
    elements_detailed: 2,
    history_gaps_count: 0,
  },
  attribution: {
    copyright: "OpenStreetMap contributors",
    attribution: "https://www.openstreetmap.org/copyright",
    license: "Open Database License 1.0",
  },
};
