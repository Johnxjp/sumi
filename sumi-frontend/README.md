# sumi-frontend

The web chat page for sumi: a single page that sends your question to the
Python backend and shows the agent's reply as it streams in. Design and
protocol: `../docs/designs/chat-ui.md`.

## Run

Start the backend first, from `../sumi-backend`:

```
uv run uvicorn src.chat.app:app --port 8766
```

Then, here:

```
pnpm install
pnpm dev        # → http://localhost:3000
```

The page expects the backend at `http://localhost:8766`; set
`NEXT_PUBLIC_API_URL` in `.env.local` to change that.

## Check

```
pnpm test       # Vitest: the stream parser and message logic in lib/
pnpm lint       # ESLint
pnpm build      # type-checks and builds
```
