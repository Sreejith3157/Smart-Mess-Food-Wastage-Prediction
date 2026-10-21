/* Chart.js rendering. Data is passed from Flask as JSON in #chart-data. */
(function () {
  "use strict";
  var holder = document.getElementById("chart-data");
  if (!holder || !window.Chart) { return; }
  var d = JSON.parse(holder.textContent);

  var GREEN = "#2a7a4f", TOMATO = "#c8452e", TURMERIC = "#e0a106", INK = "#1b2a24";
  Chart.defaults.font.family = '"Bricolage Grotesque", system-ui, sans-serif';
  Chart.defaults.color = "#5d6f66";
  Chart.defaults.maintainAspectRatio = false;
  Chart.defaults.plugins.legend.labels.usePointStyle = true;

  function make(id, config) {
    var el = document.getElementById(id);
    if (el) { new Chart(el, config); }
  }

  if (d.page === "dashboard") {
    make("dailyChart", {
      data: {
        labels: d.daily.labels,
        datasets: [
          { type: "bar", label: "Prepared (kg)", data: d.daily.prepared, backgroundColor: GREEN, borderRadius: 3, order: 2 },
          { type: "bar", label: "Wasted (kg)", data: d.daily.wasted, backgroundColor: TOMATO, borderRadius: 3, order: 2 },
          { type: "line", label: "Wastage %", data: d.daily.pct, borderColor: TURMERIC, backgroundColor: TURMERIC,
            yAxisID: "y1", tension: .3, pointRadius: 2, order: 1 }
        ]
      },
      options: {
        interaction: { mode: "index", intersect: false },
        scales: {
          x: { ticks: { maxRotation: 60, autoSkip: true, maxTicksLimit: 10 }, grid: { display: false } },
          y: { title: { display: true, text: "kg per day" }, beginAtZero: true },
          y1: { position: "right", title: { display: true, text: "Wastage %" }, beginAtZero: true, grid: { drawOnChartArea: false } }
        }
      }
    });
    make("mealChart", {
      type: "bar",
      data: {
        labels: d.meal.labels,
        datasets: [
          { label: "Prepared (kg)", data: d.meal.prepared, backgroundColor: GREEN, borderRadius: 4 },
          { label: "Wasted (kg)", data: d.meal.wasted, backgroundColor: TOMATO, borderRadius: 4 }
        ]
      },
      options: { scales: { y: { beginAtZero: true, title: { display: true, text: "kg (total)" } }, x: { grid: { display: false } } } }
    });
    make("splitChart", {
      type: "doughnut",
      data: { labels: ["Consumed (kg)", "Wasted (kg)"], datasets: [{ data: [d.split.consumed, d.split.wasted], backgroundColor: [GREEN, TOMATO], borderWidth: 0 }] },
      options: { cutout: "62%" }
    });
  }

  if (d.page === "performance") {
    var pts = d.points.map(function (p) { return { x: p.actual, y: p.predicted }; });
    var lo = Math.min.apply(null, d.points.map(function (p) { return Math.min(p.actual, p.predicted); }));
    var hi = Math.max.apply(null, d.points.map(function (p) { return Math.max(p.actual, p.predicted); }));
    make("scatterChart", {
      type: "scatter",
      data: {
        datasets: [
          { label: "Test samples", data: pts, backgroundColor: "rgba(42,122,79,.65)", pointRadius: 3 },
          { type: "line", label: "Perfect prediction", data: [{ x: lo, y: lo }, { x: hi, y: hi }], borderColor: TURMERIC, borderDash: [6, 4], pointRadius: 0, borderWidth: 2 }
        ]
      },
      options: { scales: { x: { title: { display: true, text: "Actual wastage (kg)" } }, y: { title: { display: true, text: "Predicted wastage (kg)" } } } }
    });
    var firstN = d.points.slice(0, 50);
    make("seriesChart", {
      type: "line",
      data: {
        labels: firstN.map(function (_, i) { return i + 1; }),
        datasets: [
          { label: "Actual", data: firstN.map(function (p) { return p.actual; }), borderColor: INK, backgroundColor: INK, tension: .25, pointRadius: 2 },
          { label: "Predicted", data: firstN.map(function (p) { return p.predicted; }), borderColor: GREEN, backgroundColor: GREEN, tension: .25, pointRadius: 2 }
        ]
      },
      options: { scales: { x: { title: { display: true, text: "Test sample #" } }, y: { title: { display: true, text: "Wastage (kg)" }, beginAtZero: true } } }
    });
    make("importanceChart", {
      type: "bar",
      data: { labels: d.importance.map(function (r) { return r.feature; }),
              datasets: [{ label: "Importance", data: d.importance.map(function (r) { return r.importance; }), backgroundColor: GREEN, borderRadius: 4 }] },
      options: { indexAxis: "y", plugins: { legend: { display: false } }, scales: { x: { beginAtZero: true } } }
    });
  }
})();
