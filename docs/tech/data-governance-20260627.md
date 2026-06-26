# Data Governance Run - 2026-06-27

## Scope

- Clean deleted knowledge points and questions.
- Verify canonical chapter retrieval segments.
- Build chapter relations for review.

## Results

- Physically deleted 12 `knowledge_points` rows with `status = 'deleted'`.
- Physically deleted 24 `questions` rows with `status = 'deleted'`.
- Verified no remaining deleted knowledge points or questions.
- Verified canonical chapter segments:
  - `canonical_chapter/title`: 339
  - `canonical_chapter/content`: 255
  - total: 594
- Verified pending questions:
  - pending questions: 20
  - missing `primary_chapter_id`: 0
- Built `chapter_relations` with embedding fallback:
  - processed chapters: 339
  - created relations: 196
  - `source_type = 'embedding'`
  - `review_status = 'pending'`

## Deferred

- `canonical_chapters.cross_references` remains empty: 0 / 339 active chapters.
- LLM cross-reference enrichment was attempted for `subj_ds`, but the script timed out before committing chapter updates. The generated LLM call logs remain for audit, but no `cross_references` were written.
- Further LLM cross-reference enrichment is intentionally deferred to avoid consuming long-prompt quota.

## Fix Applied

- Fixed `/admin/chapter-relations/build` to deduplicate relation keys in memory before flush.
- Fixed the same endpoint's `outline_id` parameter spelling so frontend filtering works.
