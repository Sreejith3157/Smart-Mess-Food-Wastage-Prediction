/* General UI behaviour: password toggle, confirmations, loading buttons,
   upload checks and the day-type suggestion on the prediction form. */
(function () {
  "use strict";

  var toggle = document.getElementById("togglePassword");
  if (toggle) {
    toggle.addEventListener("click", function () {
      var input = document.getElementById("password");
      var show = input.type === "password";
      input.type = show ? "text" : "password";
      toggle.setAttribute("aria-label", show ? "Hide password" : "Show password");
      toggle.firstElementChild.className = show ? "bi bi-eye-slash" : "bi bi-eye";
    });
  }

  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (e) {
      if (!window.confirm(form.getAttribute("data-confirm"))) { e.preventDefault(); }
    });
  });

  document.querySelectorAll("form[data-loading-form]").forEach(function (form) {
    form.addEventListener("submit", function (e) {
      if (e.defaultPrevented) { return; }
      var btn = form.querySelector("button[type=submit]");
      if (!btn) { return; }
      var text = form.getAttribute("data-loading-text") || "Please wait…";
      setTimeout(function () {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2" aria-hidden="true"></span>' + text;
      }, 0);
    });
  });

  var file = document.getElementById("csvFile");
  if (file) {
    file.addEventListener("change", function () {
      var f = file.files[0];
      var max = parseInt(file.getAttribute("data-max-mb"), 10) * 1024 * 1024;
      var msg = document.getElementById("fileMsg");
      msg.textContent = "";
      if (!f) { return; }
      if (!/\.csv$/i.test(f.name)) { msg.textContent = "Please choose a .csv file."; file.value = ""; }
      else if (f.size > max) { msg.textContent = "File is larger than the " + (max / 1048576) + " MB limit."; file.value = ""; }
    });
  }

  var dateInput = document.getElementById("meal_date");
  var dayType = document.getElementById("day_type");
  if (dateInput && dayType) {
    var suggest = function () {
      if (dayType.value === "Holiday" || !dateInput.value) { return; }
      var d = new Date(dateInput.value + "T00:00:00");
      if (isNaN(d.getTime())) { return; }
      var weekend = d.getDay() === 0 || d.getDay() === 6;
      dayType.value = weekend ? "Weekend" : "Weekday";
    };
    dateInput.addEventListener("change", suggest);
    if (!dayType.value) { suggest(); }
  }

  document.querySelectorAll(".alert-success.alert-dismissible").forEach(function (el) {
    setTimeout(function () {
      if (window.bootstrap && document.body.contains(el)) { bootstrap.Alert.getOrCreateInstance(el).close(); }
    }, 7000);
  });
})();
