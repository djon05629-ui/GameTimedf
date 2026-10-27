// Подтверждение опасных действий: <form data-confirm="Текст вопроса">
(function () {
  var dialog = document.getElementById("confirm-dialog");
  document.addEventListener("submit", function (ev) {
    var form = ev.target;
    var text = form.getAttribute("data-confirm");
    if (!text) return;
    ev.preventDefault();
    if (!dialog || typeof dialog.showModal !== "function") {
      if (window.confirm(text)) { form.removeAttribute("data-confirm"); form.submit(); }
      return;
    }
    document.getElementById("confirm-text").textContent = text;
    dialog.returnValue = "";
    dialog.showModal();
    dialog.addEventListener("close", function onClose() {
      dialog.removeEventListener("close", onClose);
      if (dialog.returnValue === "ok") { form.removeAttribute("data-confirm"); form.submit(); }
    });
  });
})();
