const API = location.origin;
let symbol = "XAUUSD", chart, candleSeries, candles = [], strategies = [];
const $ = id => document.getElementById(id);
const money = n => (n < 0 ? "-$" : "$") + Math.abs(Number(n || 0)).toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:2});
function toast(message){const el=$("toast");el.textContent=message;el.classList.add("show");setTimeout(()=>el.classList.remove("show"),2300);}
async function api(path, options={}){const response=await fetch(API+path,{headers:{"Content-Type":"application/json"},...options});const data=await response.json();if(!response.ok)throw new Error(data.detail||"Request failed");return data;}
function initChart(){
 chart=LightweightCharts.createChart($("chart"),{layout:{background:{color:"#111a2d"},textColor:"#91a0ba"},grid:{vertLines:{color:"#1c2940"},horzLines:{color:"#1c2940"}},rightPriceScale:{borderColor:"#293852"},timeScale:{borderColor:"#293852",timeVisible:true},crosshair:{mode:1}});
 candleSeries=chart.addCandlestickSeries({upColor:"#28d6a1",downColor:"#ff6b7a",borderUpColor:"#28d6a1",borderDownColor:"#ff6b7a",wickUpColor:"#28d6a1",wickDownColor:"#ff6b7a"});
 new ResizeObserver(()=>chart.applyOptions({width:$("chart").clientWidth})).observe($("chart"));
}
async function loadCandles(){candles=await api("/api/candles/"+symbol);candleSeries.setData(candles);chart.timeScale().fitContent();const last=candles[candles.length-1];$("lastPrice").textContent=Number(last.close).toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:2});}
function updateChart(price){const last=candles[candles.length-1];if(!last)return;const t=Math.floor(Date.now()/1000);const c={time:Math.max(t,last.time+1),open:last.close,high:Math.max(last.close,price),low:Math.min(last.close,price),close:price};candleSeries.update(c);candles.push(c);if(candles.length>300)candles.shift();$("lastPrice").textContent=Number(price).toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:2});}
function renderPositions(positions,quotes){
 $("positionsBody").innerHTML=positions.length?positions.map(p=>{const mark=quotes[p.symbol]?.price ?? p.entry;const pnl=(mark-p.entry)*p.quantity*(p.side==="BUY"?1:-1);return '<tr><td><b>'+p.symbol+'</b></td><td class="'+(p.side==="BUY"?"side-buy":"side-sell")+'">'+p.side+'</td><td>'+p.quantity+'</td><td>'+p.entry.toFixed(2)+'</td><td>'+mark.toFixed(2)+'</td><td class="'+(pnl>=0?"good":"bad")+'">'+money(pnl)+'</td><td><button class="close" data-close="'+p.id+'">Close</button></td></tr>';}).join(""):'<tr><td colspan="7" class="empty">No open positions</td></tr>';
}
function renderHistory(history){$("historyBody").innerHTML=history.length?history.slice().reverse().map(p=>'<tr><td><b>'+p.symbol+'</b></td><td>'+p.side+'</td><td>'+p.entry.toFixed(2)+'</td><td>'+p.exit.toFixed(2)+'</td><td class="'+(p.pnl>=0?"good":"bad")+'">'+money(p.pnl)+'</td><td>'+p.reason+'</td></tr>').join(""):'<tr><td colspan="6" class="empty">No completed trades</td></tr>';}
async function refresh(){
 const [account,quotes]=await Promise.all([api("/api/account"),api("/api/quotes")]);
 $("balance").textContent=money(account.balance);$("equity").textContent=money(account.equity);
 $("realized").textContent=money(account.realized_pnl);$("unrealized").textContent=money(account.unrealized_pnl);
 $("realized").className=account.realized_pnl>=0?"good":"bad";$("unrealized").className=account.unrealized_pnl>=0?"good":"bad";
 $("botStatus").textContent=account.auto?"● AUTO TRADING RUNNING":"● AUTO TRADING STOPPED";
 $("autoBtn").disabled=account.auto;$("stopBtn").disabled=!account.auto;
 renderPositions(account.positions,quotes);renderHistory(account.history);
 $("positionCount").textContent=account.positions.length;$("historyCount").textContent=account.history.length;
 return {account,quotes};
}
function renderStrategies(){
 const q=$("strategySearch").value.toLowerCase();
 const list=strategies.filter(s=>(s.name+" "+s.category).toLowerCase().includes(q));
 $("strategyCount").textContent=strategies.length;
 $("strategyList").innerHTML=list.map(s=>'<div class="strategy"><div><b>'+s.name+'</b><small>'+s.category+' · '+s.rule_summary+'</small></div><em>'+(s.executable?"READY · DEMO":s.status==="research_required"?"RESEARCH ONLY":"TEMPLATE ONLY")+'</em></div>').join("");
}
async function loadStrategies(){strategies=await api("/api/strategies");const runnable=strategies.filter(s=>s.executable);$("autoStrategy").innerHTML=runnable.map(s=>'<option value="'+s.id+'">'+s.name+'</option>').join("");renderStrategies();}
async function refreshFeeds(){
 try{
  const health=await api("/api/health");
  const label=(s)=>health.feeds[s]==="connected"?"LIVE":health.feeds[s]==="missing_credentials"?"API KEY REQUIRED":health.feeds[s].toUpperCase();
  $("xauFeed").textContent="XAUUSD · "+label("XAUUSD");
  $("btcFeed").textContent="BTCUSD · "+label("BTCUSD");
  const live=Object.values(health.live_ready||{}).every(Boolean);
  $("feedStatus").textContent=live?"LIVE MARKET DATA":"LIVE FEEDS NOT READY";
  $("feedStatus").classList.toggle("live",live);
 }catch(error){$("feedStatus").textContent="FEED STATUS UNAVAILABLE";}
}
async function place(side){
 try{const body={symbol:$("orderSymbol").value,side,quantity:Number($("quantity").value),stop_loss:$("sl").value?Number($("sl").value):null,take_profit:$("tp").value?Number($("tp").value):null};await api("/api/orders",{method:"POST",body:JSON.stringify(body)});toast(side+" paper order opened");await refresh();}catch(e){toast(e.message);}
}
$("buyBtn").onclick=()=>place("BUY");$("sellBtn").onclick=()=>place("SELL");
$("resetBtn").onclick=async()=>{const value=prompt("Enter new starting paper balance (USD):","10000");if(value===null)return;try{await api("/api/account/reset",{method:"POST",body:JSON.stringify({balance:Number(value)})});toast("Paper account reset");await refresh();}catch(e){toast(e.message);}};
$("autoBtn").onclick=async()=>{try{await api("/api/auto",{method:"POST",body:JSON.stringify({enabled:true,strategy_id:$("autoStrategy").value,risk_pct:Number($("risk").value)})});toast("Auto paper trading started");await refresh();}catch(e){toast(e.message);}};
$("stopBtn").onclick=async()=>{try{await api("/api/auto",{method:"POST",body:JSON.stringify({enabled:false,risk_pct:Number($("risk").value)})});toast("Auto trading stopped");await refresh();}catch(e){toast(e.message);}};
$("risk").oninput=()=>{$("riskLabel").textContent=Number($("risk").value).toFixed(2)+"%";};
$("strategySearch").oninput=renderStrategies;
$("saveCustom").onclick=async()=>{try{const body={name:$("customName").value,symbol:"BOTH",fast_ema:Number($("fastEma").value),slow_ema:Number($("slowEma").value),direction:"both"};const item=await api("/api/strategies/custom",{method:"POST",body:JSON.stringify(body)});strategies.push(item);renderStrategies();toast("Custom strategy saved as a draft");}catch(e){toast(e.message);}};
$("positionsBody").onclick=async event=>{const id=event.target.dataset.close;if(id){try{await api("/api/positions/"+id+"/close",{method:"POST"});toast("Position closed");await refresh();}catch(e){toast(e.message);}}};
document.querySelectorAll("[data-symbol]").forEach(button=>button.onclick=async()=>{symbol=button.dataset.symbol;document.querySelectorAll("[data-symbol]").forEach(b=>b.classList.toggle("active",b===button));$("chartTitle").textContent=symbol+(symbol==="XAUUSD"?" · Gold / US Dollar":" · Bitcoin / US Dollar");await loadCandles();});
async function boot(){initChart();await loadStrategies();await loadCandles().catch(()=>{});await refresh();await refreshFeeds();setInterval(async()=>{try{const result=await refresh();if(result.quotes[symbol])updateChart(result.quotes[symbol].price);}catch(error){console.error(error);}},2200);setInterval(refreshFeeds,15000);}
boot().catch(error=>toast(error.message));
