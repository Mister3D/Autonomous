function pad2(n) {
  return String(n).padStart(2, "0");
}

/** { date: "DD/MM"|"" , time: "HH:MM"|"" } — date only if older than today. */
export function formatMsgStamp(iso, locale = "fr") {
  if (!iso) return { date: "", time: "" };
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return { date: "", time: "" };
  const now = new Date();
  const sameDay =
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate();
  const time = d.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" });
  const date = sameDay ? "" : `${pad2(d.getDate())}/${pad2(d.getMonth() + 1)}`;
  return { date, time };
}

/** Single-line stamp for compact UI (tools). */
export function formatMsgTime(iso, locale = "fr") {
  const { date, time } = formatMsgStamp(iso, locale);
  if (!time) return "";
  return date ? `${date} ${time}` : time;
}
