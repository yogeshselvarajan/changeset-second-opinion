# Edit-time changeset count backfill (2026-10-17)

Counts only; no names. The evidence used to show each author's current changeset total.
The changeset's own `changesets_count` tag holds the count when the edit was made.

| Measure | Items |
|---|---|
| cached snapshots | 162 |
| already patched before this run | 0 |
| fetched this run | 162 |
| fetch failed (left unchanged) | 0 |
| tag present: edit-time count used | 128 |
| tag absent: current total kept, labelled `current` | 34 |
| edit-time count differs from the stored total | 97 |

## Effect on the parsed `new_account` fact

(account under 7 days old, or under 10 changesets at the time)

| | Items |
|---|---|
| true before the patch | 117 |
| true after the patch | 121 |
| unknown after the patch | 16 |
| fact differs before vs after | 29 |

An unknown means only a current total of 10 or more is available, which cannot show the
edit-time count was 10 or more. Unknown readings count as cautious in the composition.
