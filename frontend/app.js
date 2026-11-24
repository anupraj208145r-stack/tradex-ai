const API = location.origin;
let symbol = "XAUUSD", timeframe = "1m", chart, candleSeries, candles = [], strategies = [], riskLines = [], overlayLines = [];
let ws=null, reconnectDelay=1000, lastAccountPaint=0, botRunning=false, activeStrategyId="STR-001", chartBarSpacing=8, latestQuotes={};
const $ = id => document.getElementById(id);
const CONTRACT_SIZE = {XAUUSD:100, BTCUSD:1};
const money = n => (n < 0 ? "-$" : "$") + Math.abs(Number(n || 0)).toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:2});
function toast(message){const el=$("toast");el.textContent=message;el.classList.add("show");setTimeout(()=>el.classList.remove("show"),2300);}
async function api(path, options={}){const token=await window.getTradeXAccessToken?.();if(!token)throw new Error("Please sign in again.");const response=await fetch(API+path,{...options,headers:{"Content-Type":"application/json",...(options.headers||{}),"Authorization":"Bearer "+token}});const data=await response.json();if(!response.ok)throw new Error(data.detail||"Request failed");return data;}
function initChart(){
 const el=$("chart");
 chart=LightweightCharts.createChart(el,{
  autoSize:true,
  layout:{background:{type:"solid",color:"#19131f"},textColor:"#b8b2c4",fontFamily:"Inter, system-ui, sans-serif",fontSize:11},
  grid:{vertLines:{color:"#302333",style:1},horzLines:{color:"#302333",style:1}},
  rightPriceScale:{borderColor:"#493344",minimumWidth:64,scaleMargins:{top:.08,bottom:.08}},
  timeScale:{borderColor:"#493344",timeVisible:true,secondsVisible:false,rightOffset:6,barSpacing:chartBarSpacing,borderVisible:true},
  crosshair:{mode:1,vertLine:{color:"#b56b83",width:1,style:2,labelBackgroundColor:"#71364d"},horzLine:{color:"#b56b83",width:1,style:2,labelBackgroundColor:"#71364d"}},
  handleScroll:{mouseWheel:true,pressedMouseMove:true},
  handleScale:{mouseWheel:true,pinch:true},
  localization:{locale:"en-US"}
 });
 candleSeries=chart.addCandlestickSeries({upColor:"#36d6b0",downColor:"#ff637d",borderUpColor:"#55e6c0",borderDownColor:"#ff8295",wickUpColor:"#55e6c0",wickDownColor:"#ff8295",priceLineColor:"#e2a0b2",priceLineWidth:1,priceLineStyle:2,priceLineVisible:true,lastValueVisible:true});
}
async function loadCandles(){
 const rows=await api("/api/candles/"+symbol+"?timeframe="+timeframe);
 const byTime=new Map();
 for(const c of rows){const time=Number(c.time),open=Number(c.open),high=Number(c.high),low=Number(c.low),close=Number(c.close);
  if(Number.isFinite(time)&&Number.isFinite(open)&&Number.isFinite(high)&&Number.isFinite(low)&&Number.isFinite(close)&&high>=low)byTime.set(time,{time,open,high,low,close});
 }
 candles=[...byTime.values()].sort((a,b)=>a.time-b.time).slice(-1000);
 candleSeries.setData(candles);
 if(candles.length){
  chart.timeScale().fitContent();
  $("lastPrice").textContent=Number(candles[candles.length-1].close).toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:2});
 }

 $("chartCaption").textContent=candles.length?timeframe+" candles · XAUUSD contract: 100 oz/lot · paper only":"No historical candles returned for "+symbol+" · check the market-data feed/API key";
}
function updateChart(quote){
 if(!quote||!Number.isFinite(Number(quote.price))||!Number.isFinite(Number(quote.time)))return;
 const price=Number(quote.price), step=({"1m":60,"5m":300,"15m":900,"30m":1800,"1h":3600,"4h":14400,"1d":86400})[timeframe], minute=Math.floor(Number(quote.time)/step)*step;
 const last=candles[candles.length-1];
 if(!last){const c={time:minute,open:price,high:price,low:price,close:price};candles.push(c);candleSeries.update(c);}
 else if(minute<last.time){last.high=Math.max(last.high,price);last.low=Math.min(last.low,price);last.close=price;candleSeries.update(last);}
 else if(minute===last.time){last.high=Math.max(last.high,price);last.low=Math.min(last.low,price);last.close=price;candleSeries.update(last);}
 else {const c={time:minute,open:price,high:price,low:price,close:price};candles.push(c);if(candles.length>1000)candles.shift();candleSeries.update(c);}
 $("lastPrice").textContent=price.toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:2});
 
}
function renderPositions(positions,quotes){
 const liveQuotes={...latestQuotes,...(quotes||{})};
 $("positionsBody").innerHTML=positions.length?positions.map(p=>{const mark=Number(liveQuotes[p.symbol]?.price??p.mark_price??p.entry);const pnl=Number(p.unrealized_pnl??((mark-p.entry)*p.quantity*(CONTRACT_SIZE[p.symbol]||1)*(p.side==="BUY"?1:-1)));return '<tr><td><b>'+escapeHtml(p.symbol)+'</b></td><td class="'+(p.side==="BUY"?"side-buy":"side-sell")+'">'+p.side+'</td><td>'+Number(p.quantity).toFixed(4)+'</td><td>'+Number(p.entry).toFixed(2)+'</td><td>'+mark.toFixed(2)+'</td><td>'+(p.stop_loss==null?"—":Number(p.stop_loss).toFixed(2))+'</td><td>'+(p.take_profit==null?"—":Number(p.take_profit).toFixed(2))+'</td><td class="'+(pnl>=0?"good":"bad")+'">'+money(pnl)+'</td><td><button class="close" data-close="'+escapeHtml(p.id)+'">Close</button></td></tr>';}).join(""):'<tr><td colspan="9" class="empty">No open positions</td></tr>';
 if(candleSeries){
  for(const line of riskLines)candleSeries.removePriceLine(line);
  riskLines=[];
  for(const p of positions.filter(item=>item.symbol===symbol)){
   if(p.stop_loss!=null)riskLines.push(candleSeries.createPriceLine({price:Number(p.stop_loss),color:"#ff6b7a",lineWidth:2,lineStyle:LightweightCharts.LineStyle.Dashed,axisLabelVisible:true,title:"SL"}));
   if(p.take_profit!=null)riskLines.push(candleSeries.createPriceLine({price:Number(p.take_profit),color:"#28d6a1",lineWidth:2,lineStyle:LightweightCharts.LineStyle.Dashed,axisLabelVisible:true,title:"TP"}));
  }
 }
}
function renderHistory(history){$("historyBody").innerHTML=history.length?history.slice().reverse().map(p=>'<tr><td><b>'+p.symbol+'</b></td><td>'+p.side+'</td><td>'+p.entry.toFixed(2)+'</td><td>'+p.exit.toFixed(2)+'</td><td class="'+(p.pnl>=0?"good":"bad")+'">'+money(p.pnl)+'</td><td>'+p.reason+'</td></tr>').join(""):'<tr><td colspan="6" class="empty">No completed trades</td></tr>';}
function paintAccount(account,quotes){
 $("balance").textContent=money(account.balance);$("equity").textContent=money(account.equity);
 $("realized").textContent=money(account.realized_pnl);$("unrealized").textContent=money(account.unrealized_pnl);
 $("realized").className=account.realized_pnl>=0?"good":"bad";$("unrealized").className=account.unrealized_pnl>=0?"good":"bad";
 botRunning=!!account.auto;activeStrategyId=account.active_strategy||activeStrategyId;
 $("botStatus").textContent=account.auto?"● AUTO TRADING RUNNING · "+(account.active_timeframe||"1m"):"● AUTO TRADING STOPPED";
 $("autoBtn").disabled=account.auto;$("stopBtn").disabled=!account.auto;
 renderPositions(account.positions,quotes);renderHistory(account.history);
 $("positionCount").textContent=account.positions.length;$("historyCount").textContent=account.history.length;
}
async function refresh(){const [account,quotes]=await Promise.all([api("/api/account"),api("/api/quotes")]);Object.assign(latestQuotes,quotes||{});paintAccount(account,latestQuotes);return {account,quotes};}
function escapeHtml(value){return String(value??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
function renderStrategies(){
 const q=$("strategySearch").value.toLowerCase(),list=strategies.filter(s=>(s.name+" "+s.category).toLowerCase().includes(q));
 $("strategyCount").textContent=strategies.length;
 $("strategyList").innerHTML=list.map(s=>'<div class="strategy"><div><b>'+escapeHtml(s.name)+'</b><small>'+escapeHtml(s.category)+' · '+escapeHtml(s.rule_summary)+'</small></div><em>'+(s.executable?"IMPLEMENTED · PAPER":s.status==="research_required"?"RESEARCH ONLY":"TEMPLATE ONLY")+'</em></div>').join("");
}
async function loadStrategies(selected){strategies=await api("/api/strategies");const runnable=strategies.filter(s=>s.executable);$("autoStrategy").innerHTML=runnable.map(s=>'<option value="'+escapeHtml(s.id)+'">'+escapeHtml(s.name)+'</option>').join("");if(selected&&runnable.some(s=>s.id===selected))$("autoStrategy").value=selected;renderStrategies();}
async function refreshFeeds(){
 try{
  const response=await fetch(API+"/api/health",{cache:"no-store"});
  if(!response.ok)throw new Error("Health endpoint returned "+response.status);
  const health=await response.json();
  const label=s=>health.live_ready?.[s]?"LIVE":health.feeds?.[s]==="missing_credentials"?"API KEY REQUIRED":(health.feeds?.[s]||"unknown").toUpperCase();
   if(!health.live_ready?.XAUUSD&&health.last_errors?.XAUUSD){$("chartCaption").textContent="XAUUSD feed: "+health.last_errors.XAUUSD+" · configure TWELVEDATA_API_KEY in Railway";}
  $("xauFeed").textContent="XAUUSD · "+label("XAUUSD");$("btcFeed").textContent="BTCUSD · "+label("BTCUSD");
  const live=Object.values(health.live_ready||{}).every(Boolean);$("feedStatus").textContent=live?"LIVE MARKET DATA":"LIVE FEEDS NOT READY";$("feedStatus").classList.toggle("live",live);
 }catch(error){$("feedStatus").textContent="FEED STATUS UNAVAILABLE";$("xauFeed").textContent="XAUUSD · STATUS UNAVAILABLE";$("btcFeed").textContent="BTCUSD · STATUS UNAVAILABLE";}
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
   if(now-lastAccountPaint>250){paintAccount(message.account,latestQuotes);lastAccountPaint=now;}
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
$("autoBtn").onclick=async()=>{try{await api("/api/auto",{method:"POST",body:JSON.stringify({enabled:true,strategy_id:$("autoStrategy").value,risk_pct:Number($("risk").value),timeframe})});toast("Auto paper trading started");await refresh();}catch(e){toast(e.message);}};
$("stopBtn").onclick=async()=>{try{await api("/api/auto",{method:"POST",body:JSON.stringify({enabled:false,risk_pct:Number($("risk").value)})});toast("Auto trading stopped");await refresh();}catch(e){toast(e.message);}};
$("risk").oninput=()=>{$("riskLabel").textContent=Number($("risk").value).toFixed(2)+"%";};
$("strategySearch").oninput=renderStrategies;
$("saveCustom").onclick=async()=>{try{const body={name:$("customName").value,symbol:"BOTH",fast_ema:Number($("fastEma").value),slow_ema:Number($("slowEma").value),direction:"both"};const item=await api("/api/strategies/custom",{method:"POST",body:JSON.stringify(body)});strategies.push(item);await loadStrategies(item.id);toast("Custom EMA strategy saved and can be selected for paper automation");}catch(e){toast(e.message);}};
$("positionsBody").onclick=async event=>{const id=event.target.dataset.close;if(id){try{await api("/api/positions/"+id+"/close",{method:"POST"});toast("Position closed");await refresh();}catch(e){toast(e.message);}}};
async function switchSymbol(next){symbol=next;const orderSymbol=$("orderSymbol");if(orderSymbol)orderSymbol.value=symbol;document.querySelectorAll("[data-symbol]").forEach(b=>b.classList.toggle("active",b.dataset.symbol===symbol));const title=$("chartTitle");if(title)title.textContent=symbol+(symbol==="XAUUSD"?" · Gold / US Dollar":" · Bitcoin / US Dollar");candles=[];if(candleSeries)candleSeries.setData([]);if(!chart||!candleSeries)throw new Error("Chart is still initializing; please try again.");await loadCandles();}
document.querySelectorAll("[data-symbol]").forEach(button=>button.onclick=()=>switchSymbol(button.dataset.symbol).catch(e=>toast("Could not load "+symbol+": "+e.message)));
$("prevSymbol").onclick=()=>switchSymbol(symbol==="XAUUSD"?"BTCUSD":"XAUUSD").catch(e=>toast(e.message));
$("nextSymbol").onclick=()=>switchSymbol(symbol==="XAUUSD"?"BTCUSD":"XAUUSD").catch(e=>toast(e.message));
document.querySelectorAll("[data-timeframe]").forEach(button=>button.onclick=async()=>{timeframe=button.dataset.timeframe;document.querySelectorAll("[data-timeframe]").forEach(b=>b.classList.toggle("active",b===button));candles=[];if(!chart||!candleSeries){toast("Chart is still initializing; please try again.");return;}candleSeries.setData([]);try{await loadCandles();if(botRunning){await api("/api/auto",{method:"POST",body:JSON.stringify({enabled:true,strategy_id:activeStrategyId,risk_pct:Number($("risk").value),timeframe})});toast("Bot timeframe changed to "+timeframe);}}catch(e){toast("Timeframe load failed: "+e.message);}});

if($("zoomIn"))$("zoomIn").onclick=()=>{if(!chart)return;chartBarSpacing=Math.min(30,chartBarSpacing*1.25);chart.timeScale().applyOptions({barSpacing:chartBarSpacing});};
if($("zoomOut"))$("zoomOut").onclick=()=>{if(!chart)return;chartBarSpacing=Math.max(2,chartBarSpacing/1.25);chart.timeScale().applyOptions({barSpacing:chartBarSpacing});};
if($("restoreChart"))$("restoreChart").onclick=()=>{if(!chart)return;chartBarSpacing=8;chart.timeScale().applyOptions({barSpacing:chartBarSpacing,rightOffset:5});chart.priceScale("right").applyOptions({autoScale:true});chart.timeScale().fitContent();};
function showView(name){
 const allowed=["trading","portfolio","positions","history","strategies"];if(!allowed.includes(name))name="trading";
 document.querySelectorAll("[data-page-view]").forEach(el=>el.classList.toggle("active",el.dataset.pageView===name));
 document.querySelectorAll("[data-view]").forEach(el=>el.classList.toggle("active",el.dataset.view===name));
 const titles={trading:["WORKSPACE / TRADING TERMINAL","Trading Terminal"],portfolio:["ACCOUNT / PERFORMANCE","Balance & P&L"],positions:["RISK MANAGEMENT","Open Positions"],history:["ACCOUNT ACTIVITY","Trade History"],strategies:["AUTOMATION / RESEARCH","Strategies & Automation"]};
 $("viewEyebrow").textContent=titles[name][0];$("viewTitle").textContent=titles[name][1];
 if(name==="trading"&&chart){requestAnimationFrame(()=>{chart.applyOptions({width:Math.max(280,$("chart").clientWidth),height:Math.max(240,$("chart").clientHeight)});});}
 history.replaceState(null,"","#"+name);
}
document.querySelectorAll("[data-view]").forEach(link=>link.addEventListener("click",event=>{event.preventDefault();showView(link.dataset.view);}));
window.addEventListener("hashchange",()=>showView(location.hash.slice(1)));
async function boot(){
 showView(location.hash.slice(1)||"trading");
 await window.authReady;
 if(!await window.getTradeXAccessToken?.())return;
 initChart();
 await refreshFeeds();
 connectMarketSocket();
 setInterval(refreshFeeds,15000);
 let activeAccount=null;
 try{
  const initial=await refresh();
  activeAccount=initial.account;
 }catch(error){
  console.error("Account bootstrap failed:",error);
  toast("Account data failed to load: "+error.message);
 }
 // Strategy loading must be independent: an account API failure must not
 // prevent the public strategy catalogue and the user's custom strategies
 // from being requested and rendered.
 try{
  await loadStrategies(activeAccount?.active_strategy);
 }catch(error){
  console.error("Strategy bootstrap failed:",error);
  $("strategyList").innerHTML='<div class="empty-state">Strategies could not be loaded: '+escapeHtml(error.message)+'. Please refresh after checking your session.</div>';
  $("strategyCount").textContent="0";
  toast("Strategies failed to load: "+error.message);
 }
 try{await loadCandles();}catch(error){console.error("Candle load failed:",error);$("chartCaption").textContent="Historical candles unavailable · checking live feed";}
}
boot().catch(error=>toast(error.message));
