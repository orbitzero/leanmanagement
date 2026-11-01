(function () {
  // Prevent double submission and give immediate feedback.
  document.addEventListener('submit', function (e) {
    var btns = e.target.querySelectorAll('button:not([type=button])');
    setTimeout(function () { btns.forEach(function (b) { b.disabled = true; }); }, 0);
  });
  // Auto-dismiss success toasts; errors remain until closed.
  document.querySelectorAll('.toast:not(.error)').forEach(function (t) { setTimeout(function () { t.remove(); }, 5000); });
  document.querySelectorAll('.toast').forEach(function (t) { t.addEventListener('click', function () { t.remove(); }); });

  // Client-side status filters on tables.
  document.querySelectorAll('[data-filter-group]').forEach(function (group) {
    var rows = document.querySelectorAll('[data-status]');
    group.addEventListener('click', function (e) {
      var b = e.target.closest('button'); if (!b) return;
      group.querySelectorAll('button').forEach(function (x) { x.classList.toggle('on', x === b); });
      var f = b.dataset.f.split(',');
      rows.forEach(function (r) { r.hidden = !(b.dataset.f === 'all' || f.indexOf(r.dataset.status) > -1); });
    });
  });

  // Request form: deadline consequence is only relevant with a deadline.
  var dl = document.querySelector('[name=hard_deadline]'), cons = document.querySelector('[name=deadline_consequence]');
  if (dl && cons) {
    var sync = function () { var on = !!dl.value; cons.required = on; cons.closest('div').style.opacity = on ? 1 : .55; };
    dl.addEventListener('input', sync); sync();
  }

  // Triage panel: live score + conditional fields.
  var panel = document.querySelector('[data-triage]');
  if (panel) {
    var days = JSON.parse(panel.dataset.days), needs = JSON.parse(panel.dataset.needsReason);
    var f = panel.querySelector('form'), out = panel.querySelector('[data-score]');
    var val = function (n) { return f.elements[n].value; };
    var update = function () {
      var i = +val('impact'), c = +val('confidence'), s = val('size'), fit = +val('strategic_fit');
      out.textContent = (i && c && s) ? ((i * c / 100 * (1 + .25 * fit)) / Math.sqrt(days[s])).toFixed(2) : '—';
      var st = val('status');
      f.querySelector('[data-week]').hidden = st !== 'scheduled';
      f.querySelector('[data-req]').hidden = needs.indexOf(st) < 0;
      f.elements['decision_reason'].required = needs.indexOf(st) > -1;
      f.elements['scheduled_week'].required = st === 'scheduled';
    };
    f.addEventListener('input', update); update();
  }
})();
