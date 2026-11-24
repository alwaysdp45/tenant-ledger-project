# AI usage disclosure

AI (ChatGPT) was used only for:
1. The test cases (tenant isolation, balance, summary and audit tests).
2. The semantics: transaction behaviour, idempotency rules for bulk import, and how corrections are handled with reversal entries.

I reviewed the AI-generated tests and semantics and ran them against my implementation before submission. Items I checked: transaction handling, access-control policy, migrations, PostgreSQL concurrency behaviour and currency policy.
