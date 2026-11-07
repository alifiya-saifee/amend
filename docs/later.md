# Amend: later and spare options

Ideas and fallbacks found along the way. Each one is either needed later or kept only as a spare. None of them is in scope until it is picked on purpose.

## For a specific day
- **Speaker labels for call uploads (Wed 11):** Groq Whisper doesn't say who spoke, and rule 6 ("only confirmed parties' words") needs that. Options:
  - **AssemblyAI** or **Deepgram**: both label speakers. FreeAPIHub (7 Nov) says Deepgram gives **$200 free credit** to new accounts; check current terms. AssemblyAI is freemium;
  - Gemini audio;
  - labelling speakers by hand.

  Voice notes in the chat need none of these, because the sender is known.
- **Seeing PayPal webhooks before Render exists (Sun 8):** use **Webhook.site** (free, no key) to inspect real sandbox webhook bodies.

## Spare AI providers (only if Gemini or Groq struggles)
- **Cerebras:** very fast, same request format as Groq. FreeAPIHub (7 Nov) lists the free tier as **5 requests a minute, 1 million tokens a day, plus $5 credit**: fine as a spare, too slow-capped as a main model.

## Spare notification channel
- **Telegram Bot API** (free, no template approval): a fallback if Meta hasn't approved the WhatsApp template by Tuesday. A bot is created in minutes via BotFather. Only if WhatsApp fails; the in-app notification list stays the first fallback.
- **OpenRouter free models** (for example Nemotron 3.5 Lightning `:free`):
  - **Limits:** 20 a minute, and **50 a day** until about $10 of credits has been bought once (then 1,000 a day).
  - **Retired soon:** some free models are being retired in mid-November.

## Spare database
- **Neon** (serverless Postgres, free tier): a drop-in `DATABASE_URL` if Supabase gives trouble on Render.

## Notes on the NVIDIA checker (decide when building it)
- **Which model:** try **Nemotron 3.5 Lightning** first and **gpt-oss-20b** as the backup. Put the exact model name in an `NVIDIA_MODEL` setting.
- **Getting JSON back:** some free models don't support `response_format`, so JSON isn't enforced. If so, use tool calling, or validate with Pydantic and retry.

## Source
- freeapikeys.org: a directory that links to each provider's official sign-up. Only use keys you create yourself in the provider's own console.
