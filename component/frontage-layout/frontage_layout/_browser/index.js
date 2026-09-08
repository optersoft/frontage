// frontage-layout has no JavaScript. The protocol asks every component for an entry module,
// and an empty one is the honest answer: the stylesheet beside this file is the whole browser
// half. Keeping the file means the component needs no special case in `build`.
export default {};
