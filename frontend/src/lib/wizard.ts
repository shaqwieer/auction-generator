/**
 * The builder's three steps.
 *
 * It replaced a four-step wizard whose shape came from the spreadsheet: upload,
 * map columns, review. A booklet is not assembled that way — a cover is chosen,
 * properties are laid out and filled, and then it is generated. Importing a
 * spreadsheet is an action inside the second step, not a step of its own.
 */
export const WIZARD_STEPS = [
  "الغلاف",
  "بناء الكتيّب",
  "المراجعة والتوليد",
] as const;

/**
 * The old four steps, kept for the screens that still serve projects created
 * before the builder existed.
 */
export const LEGACY_WIZARD_STEPS = [
  "القالب",
  "مصدر البيانات",
  "ربط الأعمدة",
  "المراجعة والتوليد",
] as const;
