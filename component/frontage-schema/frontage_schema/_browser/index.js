// frontage-schema has no JavaScript. Validation is Python, on both interpreters, and the
// protocol asks every component for an entry module: an empty one is the honest answer, and
// keeping the file means the component needs no special case in `build`. The stylesheet
// beside this file styles the one element the form half emits, `.fr-error`.
export default {};
