# Dev labels: web-verification notes (session `s2-web-verified`, labeller `claude`)

These labels are produced by an AI (Claude), not by a person, and are not human ground truth.
Every one of the 60 dev changesets was opened on openstreetmap.org (public pages, read-only,
one at a time) before labelling, and the element histories listed below were also read. Mapper
names are intentionally omitted; items are identified by changeset id.

## Systematic finding: the evidence's changeset count is not the count at edit time
The USER block shows each account's *current* changeset total at fetch time. The changeset's own
`changesets_count` tag shows the count when the edit was made. Examples: 185610206 shows 29 but
was 5; 185592201 shows 120 but was 1; 185612339 shows 1242 but was 80. Account age is measured at
edit time (correct), so only the changeset count is skewed. Effect: the `new_account_first_edits`
probe ("fewer than 10 changesets") is answered with the wrong number by both the labelling view and
the Decider's input. Where the page gives the at-edit-time count it was used here.

## Changes from the first pass (session `s1`), 9 items
- 183627357 (index 23) and 185286891 (45): `new_account_first_edits` no -> yes (8 and 9 changesets at edit time).
- 185611705 (51): `new_account_first_edits` no -> unknown (no at-edit-time count published).
- 185284243 (9) and 185282028 (31): names follow a consistent operator scheme (`CNRL ...`), so not nonsense.
- 185281778 (13) and 185283038 (17): element history shows old import road segments merged into a longer named way and never restored; the comment is imprecise but the edit is not damage -> consistent_edit.
- 183637455 (14): the changeset comment itself states the source (local knowledge, town-hall visit) -> consistent_edit.
- 185580247 (54): an experienced mapper's thread advises a different access tag and the author agrees to revise -> likely_good_faith_mistake.

## Element histories read
- way 30457746 (item 13): Geobase 2009 import segment, deleted in the changeset, never restored.
- way 947988041 (item 46): secondary highway deleted about 3 hours before the check; replacement not confirmed -> stays needs_local_knowledge.
- way 367091612 (item 48): cadastre building deleted with comment "."; never restored -> stays needs_local_knowledge.
- way 1233060263 (item 56): GNIS helipad replaced by a corrected helispot area in the same changeset.
- node 2144825177 (item 2): one unmentioned theatre-node deletion inside a sourced data-enrichment edit.
- way 336419953 (item 0): standard `disused:` lifecycle tagging; closure itself is not verifiable from OSM.

## Limits
Single AI labeller. No clear deliberate-damage example exists in the pool. `discussion_cites_source`
is "no" for all 60. Some discussions record later reverts (hindsight the Decider also sees).
