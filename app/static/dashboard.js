"use strict";

const state = { data: null, day: null, specialty: "all", status: "all", request: 0, controller: null, datesKey: "", doctorsKey: "", appointmentsKey: "" };
const byId = (id) => document.getElementById(id);
const appointmentChanges = new Map();
let noticeTimer;

function highlightChanges() {
  const inCallPanel = byId("call-dialog").open;
  for (const [id, change] of appointmentChanges) {
    if (!inCallPanel && Date.now() > change.until) appointmentChanges.delete(id);
  }
  for (const row of document.querySelectorAll("[data-appointment-id]")) {
    const change = appointmentChanges.get(row.dataset.appointmentId);
    row.classList.toggle("appointment-changed", Boolean(change));
    if (change) row.dataset.action = change.action;
    else delete row.dataset.action;
  }
  for (const card of document.querySelectorAll("[data-doctor-id]")) {
    card.classList.toggle("appointment-changed", [...appointmentChanges.values()].some(change => change.doctorId === card.dataset.doctorId));
  }
}

function showAppointmentNotice(action) {
  clearTimeout(noticeTimer);
  const notice = byId("appointment-notice");
  notice.textContent = action === "cancelled" ? "Appointment cancelled. The time is available again." : "Appointment booked. Your schedule is up to date.";
  notice.hidden = false;
  noticeTimer = setTimeout(() => { notice.hidden = true; }, 6500);
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "icon");
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#i-${name}`);
  svg.append(use);
  return svg;
}

function formatTime(value) {
  return new Intl.DateTimeFormat("en-IN", { hour: "numeric", minute: "2-digit", timeZone: state.data.timezone }).format(new Date(value));
}

function localDate(value) {
  const parts = new Intl.DateTimeFormat("en-CA", { year: "numeric", month: "2-digit", day: "2-digit", timeZone: state.data.timezone }).formatToParts(new Date(value));
  const part = (type) => parts.find((item) => item.type === type).value;
  return `${part("year")}-${part("month")}-${part("day")}`;
}

function renderDates() {
  const key = JSON.stringify([state.data.dates, state.day]);
  if (key === state.datesKey) return;
  state.datesKey = key;
  const focusedDay = document.activeElement?.dataset.date;
  const buttons = state.data.dates.map((day) => {
    const date = new Date(`${day}T12:00:00Z`);
    const selected = day === state.day;
    const button = element("button", `date-button${selected ? " selected" : ""}`);
    button.type = "button";
    button.dataset.date = day;
    button.setAttribute("aria-pressed", String(selected));
    button.setAttribute("aria-label", new Intl.DateTimeFormat("en-IN", { dateStyle: "full", timeZone: "UTC" }).format(date));
    button.append(element("span", "", date.toLocaleDateString("en-IN", { weekday: "short", timeZone: "UTC" })), element("strong", "", date.getUTCDate()));
    button.addEventListener("click", () => { state.day = day; refresh(); });
    return button;
  });
  byId("date-strip").replaceChildren(...buttons);
  if (focusedDay) buttons.find((button) => button.dataset.date === focusedDay)?.focus();
}

function renderSpecialties() {
  const select = byId("specialty-filter");
  const specialties = [...new Set(state.data.doctors.map((doctor) => doctor.specialty))];
  if (select.options.length === specialties.length + 1) return;
  select.replaceChildren(new Option("All specialties", "all"), ...specialties.map((specialty) => new Option(specialty, specialty)));
  select.value = state.specialty;
}

function renderDoctors() {
  const key = JSON.stringify([state.data.doctors, state.data.slots, state.specialty]);
  if (key === state.doctorsKey) return;
  state.doctorsKey = key;
  const doctors = state.data.doctors.filter((doctor) => state.specialty === "all" || doctor.specialty === state.specialty);
  byId("doctor-count").textContent = `${doctors.length} doctor${doctors.length === 1 ? "" : "s"}`;
  const cards = doctors.map((doctor) => {
    const card = element("article", "doctor-card");
    card.dataset.doctorId = doctor.id;
    const top = element("div", "doctor-top");
    const title = element("div");
    title.append(element("h3", "", doctor.name), element("p", "", doctor.specialty));
    top.append(element("span", `avatar ${doctor.color}`, doctor.initials), title);
    const slots = state.data.slots.filter((slot) => slot.doctor_id === doctor.id);
    const label = element("div", "slots-label");
    label.append(element("span", "", "Available times"), element("span", "", `${slots.length} open`));
    card.append(top, element("p", "doctor-description", doctor.description), label);
    if (slots.length) {
      const list = element("div", "slots");
      for (const slot of slots) {
        const time = element("time", "slot", formatTime(slot.starts_at));
        time.dateTime = slot.starts_at;
        list.append(time);
      }
      card.append(list);
    } else {
      card.append(element("p", "empty-slots", "No remaining slots on this day. Try another date."));
    }
    return card;
  });
  byId("doctor-grid").replaceChildren(...cards);
}

function renderAppointments() {
  const key = JSON.stringify([state.data.appointments, state.status]);
  if (key === state.appointmentsKey) return;
  state.appointmentsKey = key;
  const appointments = state.data.appointments.filter((appointment) => state.status === "all" || appointment.status === state.status);
  const container = byId("appointment-content");
  if (!appointments.length) {
    const empty = element("div", "empty-state");
    const mark = element("span", "empty-icon");
    mark.append(icon("calendar"));
    empty.append(mark, element("h3", "", state.status === "all" ? "A fresh page for your next patient" : `No ${state.status} appointments`), element("p", "", "Appointments will appear here as they are booked. The schedule stays in sync automatically."));
    container.replaceChildren(empty);
    return;
  }
  const scroll = element("div", "table-scroll");
  const table = element("table");
  const caption = element("caption", "sr-only", "Clinic appointments across all dates");
  const head = element("thead");
  const headers = element("tr");
  for (const title of ["Caller", "Doctor", "Date & time", "Status"]) {
    const th = element("th", "", title);
    th.scope = "col";
    headers.append(th);
  }
  head.append(headers);
  const body = element("tbody");
  for (const appointment of appointments) {
    const row = element("tr");
    row.dataset.appointmentId = appointment.id;
    row.tabIndex = -1;
    const caller = element("td", "", appointment.phone_masked);
    const doctor = element("td", "", appointment.doctor_name);
    doctor.append(element("span", "", appointment.specialty));
    const date = element("td", "", new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", year: "numeric", timeZone: state.data.timezone }).format(new Date(appointment.starts_at)));
    date.append(element("span", "", formatTime(appointment.starts_at)));
    const status = element("td");
    status.append(element("span", `status-badge ${appointment.status}`, appointment.status === "booked" ? "Booked" : "Cancelled"));
    row.append(caller, doctor, date, status);
    body.append(row);
  }
  table.append(caption, head, body);
  scroll.append(table);
  container.replaceChildren(scroll);
}

function render() {
  window.asterVoice?.updateReadiness(state.data.voice);
  window.asterCallUI?.setTimezone(state.data.timezone);
  byId("count-doctors").textContent = state.data.doctors.length;
  byId("count-slots").textContent = state.data.slots.length;
  byId("count-bookings").textContent = state.data.appointments.filter((appointment) => appointment.status === "booked" && localDate(appointment.starts_at) === state.day).length;
  byId("today-label").textContent = new Intl.DateTimeFormat("en-IN", { weekday: "short", day: "numeric", month: "long", timeZone: state.data.timezone }).format(new Date());
  byId("timezone-label").textContent = state.data.timezone;
  renderDates();
  renderSpecialties();
  renderDoctors();
  renderAppointments();
  highlightChanges();
}

async function refresh() {
  const request = ++state.request;
  state.controller?.abort();
  const controller = new AbortController();
  state.controller = controller;
  const timeout = setTimeout(() => controller.abort(), 10000);
  const requestedDay = state.day;
  try {
    const query = requestedDay ? `?day=${encodeURIComponent(requestedDay)}` : "";
    const response = await fetch(`/api/dashboard${query}`, { signal: controller.signal, cache: "no-store" });
    if (!response.ok) throw new Error(`Dashboard request failed: ${response.status}`);
    const data = await response.json();
    if (request !== state.request) return;
    state.data = data;
    state.day = data.selected_date;
    render();
    byId("connection-error").hidden = true;
    byId("sync-label").classList.remove("sync-failed");
    byId("sync-label").textContent = `Updated ${new Date().toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" })}`;
  } catch (error) {
    if (request !== state.request) return;
    byId("connection-error").hidden = false;
    byId("sync-label").textContent = state.data ? "Connection lost · showing last update" : "Clinic is offline";
    byId("sync-label").classList.add("sync-failed");
    if (!state.data) {
      byId("doctor-grid").replaceChildren(element("p", "loading-message", "The clinic could not be loaded. Use Try again to reconnect."));
      byId("appointment-content").replaceChildren(element("p", "loading-message", "Appointments are unavailable while offline."));
      byId("doctor-count").textContent = "Unavailable";
    }
  } finally {
    clearTimeout(timeout);
    if (request === state.request) {
      byId("doctors").setAttribute("aria-busy", "false");
      byId("appointment-content").setAttribute("aria-busy", "false");
      state.controller = null;
    }
  }
}

byId("specialty-filter").addEventListener("change", (event) => { state.specialty = event.target.value; if (state.data) { renderDoctors(); highlightChanges(); } });
byId("status-filter").addEventListener("change", (event) => { state.status = event.target.value; if (state.data) { renderAppointments(); highlightChanges(); } });
byId("refresh-button").addEventListener("click", refresh);
byId("retry-button").addEventListener("click", refresh);
document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
document.addEventListener("aster:appointments-updated", (event) => {
  const { action, appointment } = event.detail || {};
  if (appointment?.id && ["booked", "cancelled"].includes(action)) {
    appointmentChanges.set(appointment.id, { action, doctorId: appointment.doctor_id, until: Date.now() + 60000 });
    // Reveal the changed appointment even if a status filter would hide it.
    state.status = "all";
    byId("status-filter").value = "all";
    if (state.data && Number.isFinite(Date.parse(appointment.starts_at))) {
      const day = localDate(appointment.starts_at);
      if (state.data.dates.includes(day)) state.day = day;
    }
  }
  void refresh();
});
document.addEventListener("aster:focus-appointment", async (event) => {
  const id = event.detail?.id;
  const change = appointmentChanges.get(id);
  if (change) change.until = Date.now() + 60000;
  state.status = "all";
  byId("status-filter").value = "all";
  await refresh();
  const row = [...document.querySelectorAll("[data-appointment-id]")].find(item => item.dataset.appointmentId === id);
  if (row) {
    row.focus({ preventScroll: true });
    row.scrollIntoView({ block: "center", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth" });
    if (change) showAppointmentNotice(change.action);
  }
});
setInterval(() => { if (!document.hidden && !state.controller) refresh(); }, 5000);
refresh();
