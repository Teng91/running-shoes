// Shoe lifecycle, cost, retirement timeline, and allocation charts.
// Keep the monthly allocation readable without a tall legend below the chart.
const shoeShareLabels = {
  id: 'shoeShareLabels',
  afterDatasetsDraw(chart) {
    const dataset = chart.data.datasets[0];
    const values = dataset.data.map(Number);
    const total = values.reduce((sum, value) => sum + Math.max(0, value || 0), 0);
    if (!total) return;

    const meta = chart.getDatasetMeta(0);
    const { ctx } = chart;
    ctx.save();
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillStyle = '#fff';
    ctx.strokeStyle = 'rgba(15, 23, 42, .65)';
    ctx.lineWidth = 3;
    ctx.lineJoin = 'round';

    meta.data.forEach((arc, index) => {
      const value = values[index];
      if (!(value > 0) || arc.hidden) return;
      const angle = (arc.startAngle + arc.endAngle) / 2;
      const radius = (arc.innerRadius + arc.outerRadius) / 2;
      const x = arc.x + Math.cos(angle) * radius;
      const y = arc.y + Math.sin(angle) * radius;
      const km = Number.isInteger(value) ? String(value) : value.toFixed(1);
      const percentage = value / total * 100;

      ctx.font = '700 10px "Segoe UI", system-ui, sans-serif';
      ctx.strokeText(`${km} km`, x, y - 6);
      ctx.fillText(`${km} km`, x, y - 6);
      ctx.font = '700 9px "Segoe UI", system-ui, sans-serif';
      ctx.strokeText(`${percentage.toFixed(1)}%`, x, y + 6);
      ctx.fillText(`${percentage.toFixed(1)}%`, x, y + 6);
    });
    ctx.restore();
  }
};

function renderCharts() {
  ['progress', 'cost', 'retire', 'value'].forEach(key => {
    if (chartInstances[key]) {
      chartInstances[key].destroy();
      delete chartInstances[key];
    }
  });

  const textColor = getThemeColor('--text-dim', '#8b8d9a');
  const gridColor = getThemeColor('--chart-grid', '#2a2d3e');
  const mainTextColor = getThemeColor('--text', '#e4e4e7');

  const labels = shoes.map(s => s.brand + ' ' + s.model);
  let brandSeq = {};
  const colors = shoes.map(s => {
    brandSeq[s.brand] = (brandSeq[s.brand] || 0);
    const c = brandColor(s.brand, brandSeq[s.brand]);
    brandSeq[s.brand]++;
    return c;
  });
  const calcs = shoes.map(s => calc(s));

  chartInstances.progress = new Chart(document.getElementById('chart-progress'), {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        label: '已跑里程',
        data: shoes.map(s => s.mileage),
        backgroundColor: calcs.map(c => progressColor(c.lifeProgress)),
        borderRadius: 4,
      }, {
        label: '剩餘里程',
        data: calcs.map(c => c.remainingMileage),
        backgroundColor: '#22c55e44',
        borderColor: '#22c55e',
        borderWidth: 1,
        borderRadius: 4,
      }]
    },
    options: {
      maintainAspectRatio: false,
      indexAxis: 'y',
      plugins: {
        legend: { labels: { color: textColor, font: { size: 11 } } },
        tooltip: {
          callbacks: {
            label: ctx => {
              const shoe = shoes[ctx.dataIndex];
              const c = calcs[ctx.dataIndex];
              if (ctx.datasetIndex === 0) {
                return `已跑 ${shoe.mileage} km (${(c.lifeProgress * 100).toFixed(1)}%)`;
              }
              return `剩餘 ${c.remainingMileage} km`;
            }
          }
        }
      },
      scales: {
        x: { stacked: true, grid: { color: gridColor }, ticks: { color: textColor, callback: v => v + ' km' } },
        y: { stacked: true, grid: { display: false }, ticks: { color: textColor, font: { size: 11 }, callback: function(value) { return fitChartLabel(this.getLabelForValue(value), this.chart, 0.3); } } }
      }
    }
  });

  chartInstances.cost = new Chart(document.getElementById('chart-cost'), {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        label: '每km成本',
        data: calcs.map(c => c.costPerKm ?? 0),
        backgroundColor: colors,
        borderRadius: 4,
      }, {
        label: '預期成本',
        data: calcs.map(c => c.expectedCost),
        backgroundColor: colors.map(c => c + '44'),
        borderColor: colors,
        borderWidth: 1,
        borderRadius: 4,
      }]
    },
    options: {
      maintainAspectRatio: false,
      plugins: { legend: { labels: { color: textColor, font: { size: 11 } } }, tooltip: { callbacks: { label: ctx => '$' + ctx.raw.toFixed(2) + '/km' } } },
      scales: {
        x: { grid: { display: false }, ticks: { color: textColor, font: { size: 10 }, maxRotation: 0, callback: function(value) { return fitChartLabel(this.getLabelForValue(value), this.chart, 0.18); } } },
        y: { grid: { color: gridColor }, ticks: { color: textColor, callback: v => '$' + v } }
      }
    }
  });

  const retireData = calcs.map((c, i) => ({
    x: c.retireDate ? c.retireDate.getTime() : null,
    y: i,
    shoeIdx: i,
    label: labels[i]
  })).filter(d => d.x !== null);

  chartInstances.retire = new Chart(document.getElementById('chart-retire'), {
    type: 'scatter',
    data: {
      datasets: [{
        data: retireData.map(d => ({ x: d.x, y: d.y })),
        backgroundColor: retireData.map((d) => colors[d.shoeIdx] || '#6366f1'),
        pointRadius: 10,
        pointHoverRadius: 14,
      }]
    },
    options: {
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => {
              const d = new Date(ctx.raw.x);
              return retireData[ctx.dataIndex].label + ': ' + fmtDate(d);
            }
          }
        }
      },
      scales: {
        x: {
          type: 'linear',
          grid: { color: gridColor },
          ticks: {
            color: textColor,
            callback: v => {
              const d = new Date(v);
              return d.getFullYear() + '/' + (d.getMonth()+1);
            }
          }
        },
        y: {
          min: -1,
          max: shoes.length,
          reverse: true,
          grid: { display: false },
          ticks: {
            color: textColor,
            callback: function(v) {
              if (Number.isInteger(v) && v >= 0 && v < labels.length) return fitChartLabel(labels[v], this.chart, 0.3);
              return '';
            },
            font: { size: 10 }
          }
        }
      }
    }
  });

  const totalMonthlyKm = shoes.reduce((sum, s) => sum + s.monthly_km, 0);
  chartInstances.value = new Chart(document.getElementById('chart-value'), {
    type: 'doughnut',
    data: {
      labels,
      datasets: [{
        data: shoes.map(s => s.monthly_km),
        backgroundColor: colors,
        borderWidth: 0,
      }]
    },
    options: {
      maintainAspectRatio: false,
      cutout: '60%',
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: ctx => ctx.raw + ' km/月' } }
      }
    },
    plugins: [shoeShareLabels, {
      id: 'centerText',
      afterDraw(chart) {
        const { ctx, chartArea: { top, bottom, left, right } } = chart;
        const cx = (left + right) / 2;
        const cy = (top + bottom) / 2;
        ctx.save();
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        const h1 = 13, gap = 4, h2 = 24;
        const y0 = cy - (h1 + gap + h2) / 2;
        ctx.fillStyle = textColor;
        ctx.font = '13px "Segoe UI", system-ui, sans-serif';
        ctx.fillText('總月跑量', cx, y0);
        ctx.fillStyle = mainTextColor;
        ctx.font = 'bold 24px "Segoe UI", system-ui, sans-serif';
        ctx.fillText(totalMonthlyKm + ' km', cx, y0 + h1 + gap);
        ctx.restore();
      }
    }]
  });
}
