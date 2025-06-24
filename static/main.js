/* Gauge + live updates */
const MAX_SPEED = 100;      // km/h scale limit – edit to taste

// build a half‑doughnut gauge with Chart.js
const ctx = document.getElementById("gauge");
const gauge = new Chart(ctx, {
  type: "doughnut",
  data: {
    datasets: [{
      data: [0, MAX_SPEED],
      backgroundColor: ["#00b0ff", "#333"],
      borderWidth: 0,
      circumference: 180,
      rotation: 270,
      cutout: "70%"
    }]
  },
  options: {
    plugins:{legend:{display:false},tooltip:{enabled:false}},
    animation:false
  }
});

const lblRPM = document.getElementById("rpm");
const sock = io();

sock.on("dyno", data => {
  // update gauge
  const v = Math.min(data.speed, MAX_SPEED);
  gauge.data.datasets[0].data = [v, MAX_SPEED - v];
  gauge.update();

  // update RPM label
  lblRPM.textContent = `RPM: ${data.rpm.toFixed(0)}`;
});
