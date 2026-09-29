# SDD ledger — plan: docs/superpowers/plans/2026-09-28-nghi-frontend-onnx.md
Pre-flight: Task 1 produces {processed_text,chunks[].phoneme_ids}; Task 2 consumes the same contract — consistent with spec.
Pre-flight: Task 2 produces ID-only WAV synthesis; Task 3 only changes runtime discovery/launch — consistent with spec.
Pre-flight: Tasks 4–6 consume the same runtime/protocol without changing it — consistent with spec.
Ruling: GitHub Actions is the RED/GREEN executor because this harness cannot clone/run the repository locally; add contract commands to branch CI as tests are introduced. Production behavior remains unchanged by this ruling.
Task 1: complete (RED run #91 failed with ERR_MODULE_NOT_FOUND for tts/nghi_frontend.mjs; GREEN run #92 passed Python + Node regression including test_nghi_frontend.mjs; production commit 97606eb).
