// Выбор интервала на странице устройства. Итоговую сумму окончательно считает сервер.
(function () {
  var root = document.getElementById("booker");
  if (!root) return;
  var box = document.getElementById("slots"), dateInput = document.getElementById("b-date");
  var summary = document.getElementById("summary"), btn = document.getElementById("book-btn");
  var rate = parseFloat(root.dataset.rate), slots = [], a = null, b = null;

  function toMin(t) { var p = t.split(":"); return +p[0] * 60 + +p[1]; }
  function fmt(n) { return n.toLocaleString("ru-RU", { minimumFractionDigits: 0, maximumFractionDigits: 2 }); }

  function render() {
    box.innerHTML = "";
    slots.forEach(function (s, i) {
      var el = document.createElement("button");
      el.type = "button"; el.textContent = s.start; el.className = "slot " + (s.state === "free" ? "" : s.state);
      if (s.state !== "free") el.disabled = true;
      if (a !== null && i >= a && i <= b) el.classList.add("picked");
      el.addEventListener("click", function () { pick(i); });
      box.appendChild(el);
    });
    if (!slots.length) box.innerHTML = "<p class='muted'>На эту дату расписания нет.</p>";
    update();
  }

  function pick(i) {
    if (a === null || b !== a || i <= a) { a = b = i; }
    else {
      var ok = true;
      for (var k = a; k <= i; k++) if (slots[k].state !== "free") ok = false;
      if (ok) b = i; else { a = b = i; }
    }
    render();
  }

  function update() {
    if (a === null) { summary.textContent = "Интервал не выбран"; if (btn) btn.disabled = true; return; }
    var start = slots[a].start, end = slots[b].end;
    var minutes = toMin(end) - toMin(start), price = rate * minutes / 60;
    summary.innerHTML = start + "–" + end + " · " + (minutes / 60) + " ч · <b>" + fmt(price) + " сом</b>";
    document.getElementById("f-date") && (document.getElementById("f-date").value = dateInput.value);
    if (btn) {
      document.getElementById("f-start").value = start;
      document.getElementById("f-end").value = end;
      btn.disabled = false;
    }
  }

  function load() {
    a = b = null; box.innerHTML = "<p class='muted'>Загружаем расписание…</p>";
    fetch(root.dataset.slotsUrl + "?date=" + encodeURIComponent(dateInput.value), { headers: { Accept: "application/json" } })
      .then(function (r) { return r.json(); })
      .then(function (d) { slots = d.slots || []; render(); })
      .catch(function () { box.innerHTML = "<p class='error'>Не удалось загрузить расписание. Обновите страницу.</p>"; });
  }

  dateInput.addEventListener("change", load);
  load();
})();
