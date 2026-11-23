const API = location.origin;
let symbol = "XAUUSD", chart, candleSeries, candles = [], strategies = [];
let ws=null, reconnectDelay=1000, lastAccountPaint=0;
const $ = id => document.getElementById(id);
const money = n => (n < 0 ? "-$" : "$") + Math.abs(Number(n || 0)).toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:2});
function toast(message){const el=$("toast");el.textContent=message;el.classList.add("show");setTimeout(()=>el.classList.remove("show"),2300);}
async function api(path, options={}){const token=await window.getTradeXAccessToken?.();if(!token)throw new Error("Please sign in again.");const response=await fetch(API+path,{...options,headers:{"Content-Type":"application/json",...(options.headers||{}),"Authorization":"Bearer "+token}});const data=await response.json();if(!response.ok)throw new Error(data.detail||"Request failed");return data;}
function initChart(){
 const el=$("chart");
 chart=LightweightCharts.createChart(el,{width:el.clientWidth,height:295,layout:{background:{color:"#111a2d"},textColor:"#91a0ba"},grid:{vertLines:{color:"#1c2940"},horzLines:{color:"#1c2940"}},rightPriceScale:{borderColor:"#293852"},timeScale:{borderColor:"#293852",timeVisible:true,secondsVisible:false},crosshair:{mode:1},handleScroll:{mouseWheel:true,pressedMouseMove:true},handleScale:{mouseWheel:true,pinch:true}});
 candleSeries=chart.addCandlestickSeries({upColor:"#28d6a1",downColor:"#ff6b7a",borderUpColor:"#28d6a1",borderDownColor:"#ff6b7a",wickUpColor:"#28d6a1",wickDownColor:"#ff6b7a",priceLineVisible:true});
 let resizeFrame=0;
 new ResizeObserver(()=>{cancelAnimationFrame(resizeFrame);resizeFrame=requestAnimationFrame(()=>chart.applyOptions({width:el.clientWidth}));}).observe(el);
}
async function loadCandles(){
 const rows=await api("/api/candles/"+symbol);
 candles=rows.filter(c=>Number.isFinite(Number(c.time))&&Number.isFinite(Number(c.open))&&Number.isFinite(Number(c.high))&&Number.isFinite(Number(c.low))&&Number.isFinite(Number(c.close))).map(c=>({time:Number(c.time),open:Number(c.open),high:Number(c.high),low:Number(c.low),close:Number(c.close)}));
 candleSeries.setData(candles);
 if(candles.length) {
  chart.timeScale().fitContent();
  $("lastPrice").textContent=Number(candles[candles.length-1].close).toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:2});
 }
}
function updateChart(quote){
 if(!quote||!Number.isFinite(Number(quote.price))||!Number.isFinite(Number(quote.time)))return;
 const price=Number(quote.price), minute=Math.floor(Number(quote.time)/60)*60;
 const last=candles[candles.length-1];
 if(!last){const c={time:minute,open:price,high:price,low:price,close:price};candles.push(c);candleSeries.update(c);}
 else if(minute<last.time){$("lastPrice").textContent=price.toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:2});return;}
 else if(minute===last.time){last.high=Math.max(last.high,price);last.low=Math.min(last.low,price);last.close=price;candleSeries.update(last);}
 else {const c={time:minute,open:price,high:price,low:price,close:price};candles.push(c);if(candles.length>1000)candles.shift();candleSeries.update(c);}
 $("lastPrice").textContent=price.toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:2});
}
function renderPositions(positions,quotes){
 $("positionsBody").innerHTML=positions.length?positions.map(p=>{const mark=quotes[p.symbol]?.price??p.entry;const pnl=(mark-p.entry)*p.quantity*(p.side==="BUY"?1:-1);return '<tr><td><b>'+p.symbol+'</b></td><td class="'+(p.side==="BUY"?"side-buy":"side-sell")+'">'+p.side+'</td><td>'+p.quantity+'</td><td>'+p.entry.toFixed(2)+'</td><td>'+mark.toFixed(2)+'</td><td class="'+(pnl>=0?"good":"bad")+'">'+money(pnl)+'</td><td><button class="close" data-close="'+p.id+'">Close</button></td></tr>';}).join(""):'<tr><td colspan="7" class="empty">No open positions</td></tr>';
}
function renderHistory(history){$("historyBody").innerHTML=history.length?history.slice().reverse().map(p=>'<tr><td><b>'+p.symbol+'</b></td><td>'+p.side+'</td><td>'+p.entry.toFixed(2)+'</td><td>'+p.exit.toFixed(2)+'</td><td class="'+(p.pnl>=0?"good":"bad")+'">'+money(p.pnl)+'</td><td>'+p.reason+'</td></tr>').join(""):'<tr><td colspan="6" class="empty">No completed trades</td></tr>';}
function paintAccount(account,quotes){
 $("balance").textContent=money(account.balance);$("equity").textContent=money(account.equity);
 $("realized").textContent=money(account.realized_pnl);$("unrealized").textContent=money(account.unrealized_pnl);
 $("realized").className=account.realized_pnl>=0?"good":"bad";$("unrealized").className=account.unrealized_pnl>=0?"good":"bad";
 $("botStatus").textContent=account.auto?"● AUTO TRADING RUNNING":"● AUTO TRADING STOPPED";
 $("autoBtn").disabled=account.auto;$("stopBtn").disabled=!account.auto;
 renderPositions(account.positions,quotes);renderHistory(account.history);
 $("positionCount").textContent=account.positions.length;$("historyCount").textContent=account.history.length;
}
async function refresh(){const [account,quotes]=await Promise.all([api("/api/account"),api("/api/quotes")]);paintAccount(account,quotes);return {account,quotes};}
function renderStrategies(){
 const q=$("strategySearch").value.toLowerCase(),list=strategies.filter(s=>(s.name+" "+s.category).toLowerCase().includes(q));
 $("strategyCount").textContent=strategies.length;
 $("strategyList").innerHTML=list.map(s=>'<div class="strategy"><div><b>'+s.name+'</b><small>'+s.category+' · '+s.rule_summary+'</small></div><em>'+(s.executable?"READY · DEMO":s.status==="research_required"?"RESEARCH ONLY":"TEMPLATE ONLY")+'</em></div>').join("");
}
async function loadStrategies(){strategies=await api("/api/strategies");const runnable=strategies.filter(s=>s.executable);$("autoStrategy").innerHTML=runnable.map(s=>'<option value="'+s.id+'">'+s.name+'</option>').join("");renderStrategies();}
async function refreshFeeds(){
 try{const health=await api("/api/health");const label=s=>health.live_ready?.[s]?"LIVE":health.feeds[s]==="missing_credentials"?"API KEY REQUIRED":health.feeds[s]==="connected"?"STALE · WAITING FOR TICK":health.feeds[s].toUpperCase();
 $("xauFeed").textContent="XAUUSD · "+label("XAUUSD");$("btcFeed").textContent="BTCUSD · "+label("BTCUSD");
 const live=Object.values(health.live_ready||{}).every(Boolean);$("feedStatus").textContent=live?"LIVE MARKET DATA":"LIVE FEEDS NOT READY";$("feedStatus").classList.toggle("live",live);
 }catch(error){$("feedStatus").textContent="FEED STATUS UNAVAILABLE";}
}
function connectMarketSocket(){
 if(ws&&ws.readyState<=1)return;
 const scheme=location.protocol==="https:"?"wss":"ws";
 window.getTradeXAccessToken().then(token=>{if(!token)return;ws=new WebSocket(scheme+"://"+location.host+"/ws/market?access_token="+encodeURIComponent(token));
 ws.onopen=()=>{reconnectDelay=1000;ws.send("subscribe");};
 ws.onmessage=event=>{
  let message;try{message=JSON.parse(event.data);}catch{return;}
  const quotes=message.quotes||{};
  if(quotes[symbol])updateChart(quotes[symbol]);
  if(message.account){
   const now=Date.now();
   if(now-lastAccountPaint>1000){paintAccount(message.account,quotes);lastAccountPaint=now;}
  }
  if(message.feeds){$("btcFeed").textContent="BTCUSD · "+(message.feeds.BTCUSD||"unknown").toUpperCase();$("xauFeed").textContent="XAUUSD · "+(message.feeds.XAUUSD||"unknown").toUpperCase();}
 };
 ws.onclose=()=>{ws=null;setTimeout(connectMarketSocket,reconnectDelay);reconnectDelay=Math.min(reconnectDelay*2,15000);};
 ws.onerror=()=>{try{ws.close();}catch{}};
 });
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
async function boot(){await window.authReady;if(!await window.getTradeXAccessToken?.())return;initChart();await loadStrategies();await loadCandles().catch(()=>{});await refresh();await refreshFeeds();connectMarketSocket();setInterval(refreshFeeds,30000);}
boot().catch(error=>toast(error.message));
