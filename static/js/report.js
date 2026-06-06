document.addEventListener("DOMContentLoaded", () => {
  // Animate skill bars
  setTimeout(() => {
    const bars = document.querySelectorAll('.progress-fill');
    bars.forEach(bar => {
      // The width is already set inline, we just need to ensure the animation triggers.
      // But actually, CSS transition requires a change. 
      // Let's reset to 0 and then apply the target width from a data attribute if needed, 
      // or since we set width inline, it will animate on load if it transitions from initial state.
      // To be safe, if we set width inline, we could do this:
      const targetWidth = bar.style.width;
      bar.style.width = '0%';
      setTimeout(() => {
        bar.style.width = targetWidth;
      }, 50);
    });
  }, 100);

  // Initialize Trend Chart if Chart.js is loaded
  if (typeof Chart !== 'undefined' && document.getElementById('trendChart')) {
    const ctx = document.getElementById('trendChart').getContext('2d');

    // Use the variables injected in the template
    const labels = typeof trendLabels !== 'undefined' ? trendLabels : [];
    const data = typeof trendData !== 'undefined' ? trendData : [];

    new Chart(ctx, {
      type: 'line',
      data: {
        labels: labels.length ? labels : ['No Data'],
        datasets: [{
          label: 'Overall Score',
          data: data.length ? data : [0],
          borderColor: '#8B5CF6',
          backgroundColor: 'rgba(139, 92, 246, 0.1)',
          borderWidth: 2,
          pointBackgroundColor: '#2563EB',
          pointBorderColor: '#fff',
          pointBorderWidth: 2,
          pointRadius: 4,
          fill: true,
          tension: 0.4
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: 'rgba(255, 255, 255, 0.9)',
            titleColor: '#1f2937',
            bodyColor: '#4b5563',
            borderColor: '#e5e7eb',
            borderWidth: 1,
            padding: 10,
            displayColors: false,
          }
        },
        scales: {
          y: {
            beginAtZero: true,
            max: 10,
            grid: { color: 'rgba(0,0,0,0.05)' },
            ticks: { color: '#6b7280', stepSize: 2 }
          },
          x: {
            grid: { display: false },
            ticks: { color: '#6b7280' }
          }
        }
      }
    });
  }
});