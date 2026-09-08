// frontage-supabase has no JavaScript. Supabase's data API is PostgREST — HTTP and JSON — and
// its Realtime is a websocket, both of which MicroPython reaches through `js` directly. The
// protocol asks every component for an entry module, and an empty one is the honest answer;
// keeping the file means the component needs no special case in `build`.
//
// The alternative was supabase-js at 0.64 MB, to do what `fetch` and `WebSocket` already do.
export default {};
