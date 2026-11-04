// The same input rules as backend/services/validate.py, so the browser shows the message the server would return.
// Each check returns an error message, or "" when the value is fine.

const EMAIL_RE = /^[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*@([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,24}$/;

export const MSG = {
  email: "Enter a valid email address, like name@company.com.",
  phone: "Enter a valid phone number with country code: digits only, 10 to 15 in all.",
  name: "Enter a name using letters only (2 to 80 characters).",
  required: "This is required.",
};

export function emailError(v, required = true) {
  const s = (v || "").trim();
  if (!s) return required ? MSG.required : "";
  return s.length > 254 || !EMAIL_RE.test(s) ? MSG.email : "";
}

/** Returns { value: "+919845000000" | null, error }. A 10-digit number without a code gets the default country. */
export function normalisePhone(v, required = false, country = "91") {
  const raw = (v || "").trim();
  if (!raw) return { value: null, error: required ? MSG.required : "" };
  const plus = (raw.match(/\+/g) || []).length;
  if (/[^\d+\s\-().]/.test(raw) || plus > 1 || (plus && !raw.startsWith("+"))) return { value: null, error: MSG.phone };
  let digits = raw.replace(/\D/g, "");
  if (!raw.startsWith("+")) { digits = digits.replace(/^0+/, ""); if (digits.length === 10) digits = country + digits; }
  if (digits.length < 10 || digits.length > 15 || digits.startsWith("0")) return { value: null, error: MSG.phone };
  return { value: "+" + digits, error: "" };
}
export const phoneError = (v, required = false, country) => normalisePhone(v, required, country).error;

export function nameError(v, required = true) {
  const s = (v || "").trim().replace(/\s+/g, " ");
  if (!s) return required ? MSG.required : "";
  if (s.length < 2 || s.length > 80) return MSG.name;
  if (!/^\p{L}[\p{L}\p{M} .,'\-’]*$/u.test(s)) return MSG.name;
  // no runs of punctuation ("a--b", "A,,B"), no trailing comma: same as the server
  if ((s.match(/\p{L}/gu) || []).length < 2 || /[.,'\-’]{2,}|[ .,'\-’]{3,}/.test(s) || s.endsWith(",")) return MSG.name;
  return "";
}

export function textError(v, max = 200, required = false, label = "This") {
  const s = (v || "").trim();
  if (!s) return required ? MSG.required : "";
  return s.length > max ? `${label} can be at most ${max} characters.` : "";
}

export function intError(v, { lo, hi, required = false, label = "This" } = {}) {
  if (v === "" || v == null) return required ? MSG.required : "";
  const n = Number(v);
  if (!Number.isFinite(n) || !Number.isInteger(n)) return `${label} must be a whole number.`;
  if (lo != null && n < lo) return `${label} must be ${lo} or more.`;
  if (hi != null && n > hi) return `${label} must be ${hi} or less.`;
  return "";
}

/** Run a map of {field: () => error} and return only the fields that failed. */
export function check(rules) {
  const out = {};
  Object.entries(rules).forEach(([k, fn]) => { const e = fn(); if (e) out[k] = e; });
  return out;
}

export const COUNTRIES = [
  ["91", "India +91"], ["1", "US / Canada +1"], ["44", "UK +44"], ["971", "UAE +971"], ["65", "Singapore +65"],
  ["61", "Australia +61"], ["49", "Germany +49"], ["966", "Saudi Arabia +966"], ["974", "Qatar +974"], ["60", "Malaysia +60"],
];

/** "+919845000000" -> "+91 98450 00000" for display; other codes as "+<code> <rest>". */
export function fmtPhone(e164) {
  if (!e164) return "";
  const m = /^\+(\d+)$/.exec(e164);
  if (!m) return e164;
  const d = m[1];
  if (d.startsWith("91") && d.length === 12) return `+91 ${d.slice(2, 7)} ${d.slice(7)}`;
  const code = COUNTRIES.map((c) => c[0]).sort((a, b) => b.length - a.length).find((c) => d.startsWith(c));
  return code ? `+${code} ${d.slice(code.length)}` : "+" + d;
}

const COMMON_PASSWORDS = new Set(["password", "password1", "password123", "12345678", "123456789", "qwerty123", "iloveyou1", "admin123",
  "welcome1", "welcome123", "letmein1", "abc12345", "passw0rd", "code2hire", "code2hire1", "india123"]);
/** Same rule as the server: 8+ characters with a letter and a number, not the email name, not a very common password. */
export function passwordError(pw, email = "") {
  const p = pw || "";
  if (p.length < 8) return "Use at least 8 characters.";
  if (p.length > 128) return "Use at most 128 characters.";
  if (!/[A-Za-z]/.test(p) || !/\d/.test(p)) return "Use letters and at least one number.";
  const local = (email || "").split("@")[0].toLowerCase();
  if ((local.length >= 3 && p.toLowerCase().includes(local)) || COMMON_PASSWORDS.has(p.toLowerCase())) return "Pick something harder to guess.";
  return "";
}
