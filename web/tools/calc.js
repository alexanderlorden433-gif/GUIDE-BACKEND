/* The free calculators on /tools/. Everything runs in the browser; nothing is sent anywhere. */
(function(){
  var money = function(n){ return '$' + (isFinite(n) ? Math.round(n).toLocaleString('en-US') : '0'); };
  var money2 = function(n){ return '$' + (isFinite(n) ? n.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2}) : '0.00'); };
  var num = function(form, name){ var v = parseFloat(form.elements[name].value); return isFinite(v) && v > 0 ? v : 0; };
  var row = function(label, value){ return '<div class="row"><span>' + label + '</span><b>' + value + '</b></div>'; };

  var CALCS = {
    rate: function(f){
      var income = num(f, 'income'), costs = num(f, 'costs'), tax = Math.min(num(f, 'tax'), 80) / 100;
      var hours = num(f, 'hours'), weeks = Math.min(num(f, 'weeks'), 52);
      var billable = hours * weeks;
      if(!billable) return '<div class="row"><span>Add the hours and weeks you can work.</span></div>';
      var beforeTax = tax < 1 ? income / (1 - tax) : income;   // keep "income" after setting tax aside
      var needed = beforeTax + costs;
      var rate = needed / billable;
      return '<span>Charge at least</span><div class="big">' + money2(rate) + ' an hour</div>' +
        row('Billable hours a year', Math.round(billable).toLocaleString('en-US')) +
        row('Money the business needs to bring in', money(needed)) +
        row('Set aside for taxes', money(beforeTax - income)) +
        row('Per week, at that rate', money(rate * hours));
    },
    margin: function(f){
      var price = num(f, 'price'), cost = num(f, 'cost');
      if(!price) return '<div class="row"><span>Add what you charge.</span></div>';
      var profit = price - cost, margin = profit / price * 100, markup = cost ? profit / cost * 100 : 0;
      return '<span>You keep</span><div class="big">' + money2(profit) + ' (' + margin.toFixed(1) + '% margin)</div>' +
        row('Markup on cost', cost ? markup.toFixed(1) + '%' : '-') +
        (profit < 0 ? '<div class="row"><span>This loses money on every sale. Raise the price or cut the cost.</span></div>' : '');
    },
    price: function(f){
      var cost = num(f, 'cost'), m = Math.min(num(f, 'margin'), 95) / 100;
      var price = m < 1 ? cost / (1 - m) : cost;
      return '<span>Charge</span><div class="big">' + money2(price) + '</div>' +
        row('You keep', money2(price - cost)) +
        row('That is a markup of', cost ? ((price - cost) / cost * 100).toFixed(1) + '%' : '-');
    },
    quote: function(f){
      var labor = num(f, 'hours') * num(f, 'rate'), materials = num(f, 'materials'), travel = num(f, 'miles') * num(f, 'permile');
      var base = labor + materials + travel, buffer = base * Math.min(num(f, 'buffer'), 50) / 100;
      var total = base + buffer;
      var rounded = total >= 100 ? Math.ceil(total / 5) * 5 : Math.ceil(total);
      return '<span>Quote</span><div class="big">' + money(rounded) + '</div>' +
        row('Your time', money2(labor)) + row('Materials', money2(materials)) + row('Travel', money2(travel)) + row('Buffer', money2(buffer));
    },
  };

  document.querySelectorAll('form[data-calc]').forEach(function(form){
    var out = form.querySelector('output');
    var run = function(){ out.innerHTML = CALCS[form.dataset.calc](form); };
    form.addEventListener('input', run);
    run();
  });
})();
