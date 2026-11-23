const API = location.origin;
let symbol = "XAUUSD", timeframe = "1m", chart, candleSeries, candles = [], strategies = [], riskLines = [], overlayLines = [];
let ws=null, reconnectDelay=1000, lastAccountPaint=0, botRunning=false, activeStrategyId="STR-001", chartZones={fvg:[],order_blocks:[]}, overlayCanvas=null, overlayCtx=null, chartBarSpacing=8;
const $ = id => document.getElementById(id);
const money = n => (n < 0 ? "-$" : "$") + Math.abs(Number(n || 0)).toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:2});
function toast(message){const el=$("toast");el.textContent=message;el.classList.add("show");setTimeout(()=>el.classList.remove("show"),2300);}
async function api(path, options={}){const token=await window.getTradeXAccessToken?.();if(!token)throw new Error("Please sign in again.");const response=await fetch(API+path,{...options,headers:{"Content-Type":"application/json",...(options.headers||{}),"Authorization":"Bearer "+token}});const data=await response.json();if(!response.ok)throw new Error(data.detail||"Request failed");return data;}
function initChart(){
 const el=$("chart");
 const getSize=()=>({width:Math.max(280,Math.floor(el.getBoundingClientRect().width)),height:Math.max(240,Math.min(430,Math.floor(el.getBoundingClientRect().height||295)))});
 chart=LightweightCharts.createChart(el,{...getSize(),autoSize:true,layout:{background:{color:"#111a2d"},textColor:"#91a0ba"},grid:{vertLines:{color:"#1c2940"},horzLines:{color:"#1c2940"}},rightPriceScale:{borderColor:"#293852",minimumWidth:58},timeScale:{borderColor:"#293852",timeVisible:true,secondsVisible:false,rightOffset:5,barSpacing:chartBarSpacing},crosshair:{mode:1},handleScroll:{mouseWheel:true,pressedMouseMove:true},handleScale:{mouseWheel:true,pinch:true},localization:{locale:"en-US"}});
 candleSeries=chart.addCandlestickSeries({upColor:"#28d6a1",downColor:"#ff6b7a",borderUpColor:"#28d6a1",borderDownColor:"#ff6b7a",wickUpColor:"#28d6a1",wickDownColor:"#ff6b7a",priceLineVisible:true});
 overlayCanvas=document.createElement("canvas");overlayCanvas.className="chart-overlay";el.appendChild(overlayCanvas);overlayCtx=overlayCanvas.getContext("2d");
 const drawZones=()=>{if(!overlayCtx)return;const w=el.clientWidth,h=el.clientHeight,dpr=window.devicePixelRatio||1;overlayCanvas.width=w*dpr;overlayCanvas.height=h*dpr;overlayCanvas.style.width=w+"px";overlayCanvas.style.height=h+"px";overlayCtx.setTransform(dpr,0,0,dpr,0,0);overlayCtx.clearRect(0,0,w,h);const zones=[];if($("showFvg").checked)zones.push(...chartZones.fvg);if($("showOb").checked)zones.push(...chartZones.order_blocks);for(const z of zones){const topY=candleSeries.priceToCoordinate(Number(z.high)),botY=candleSeries.priceToCoordinate(Number(z.low));if(topY===null||botY===null)continue;const x0=chart.timeScale().timeToCoordinate(Number(z.time));const x=x0===null?0:Math.max(0,x0),top=Math.min(topY,botY),height=Math.max(2,Math.abs(botY-topY));if(x>=w)continue;const bull=z.type==="bullish",fvg=z.kind==="fvg";overlayCtx.fillStyle=fvg?(bull?"rgba(40,214,161,.14)":"rgba(255,156,112,.14)"):(bull?"rgba(113,141,255,.18)":"rgba(193,140,255,.18)");overlayCtx.strokeStyle=fvg?(bull?"#28d6a1":"#ff9c70"):(bull?"#718dff":"#c18cff");overlayCtx.fillRect(x,top,w-x,height);overlayCtx.strokeRect(x,top,w-x,height);overlayCtx.fillStyle="#e9effb";overlayCtx.font="10px sans-serif";overlayCtx.fillText((fvg?"FVG ":"OB ")+z.type.toUpperCase(),x+4,Math.max(12,top+12));}};
 window.drawTradeXZones=drawZones;chart.subscribeVisibleLogicalRangeChange(drawZones);chart.timeScale().subscribeVisibleTimeRangeChange(drawZones);
 let resizeFrame=0;
 const observer=new ResizeObserver(()=>{cancelAnimationFrame(resizeFrame);resizeFrame=requestAnimationFrame(()=>{const size=getSize();chart.applyOptions(size);drawZones();});});
 observer.observe(el);
 window.addEventListener("beforeunload",()=>observer.disconnect(),{once:true});
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
 await loadAnalysis();
 $("chartCaption").textContent=timeframe+" candles · both market scanners operate independently · paper only";
}
async function loadAnalysis(){try{const data=await api("/api/analysis/"+symbol+"?timeframe="+timeframe);chartZones={fvg:(data.fvg||[]).map(z=>({...z,kind:"fvg"})),order_blocks:(data.order_blocks||[]).map(z=>({...z,kind:"ob"}))};}catch(e){console.warn(e);chartZones={fvg:[],order_blocks:[]};}if(overlayCanvas){const w=$("chart").clientWidth,h=$("chart").clientHeight,dpr=window.devicePixelRatio||1;overlayCanvas.width=w*dpr;overlayCanvas.height=h*dpr;overlayCtx.clearRect(0,0,w,h);window.drawTradeXZones?.();chart.timeScale().scrollToRealTime();}}

function updateChart(quote){
 if(!quote||!Number.isFinite(Number(quote.price))||!Number.isFinite(Number(quote.time)))return;
 const price=Number(quote.price), step=({"1m":60,"5m":300,"15m":900,"30m":1800,"1h":3600,"4h":14400,"1d":86400})[timeframe], minute=Math.floor(Number(quote.time)/step)*step;
 const last=candles[candles.length-1];
 if(!last){const c={time:minute,open:price,high:price,low:price,close:price};candles.push(c);candleSeries.update(c);}
 else if(minute<last.time){$("lastPrice").textContent=price.toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:2});return;}
 else if(minute===last.time){last.high=Math.max(last.high,price);last.low=Math.min(last.low,price);last.close=price;candleSeries.update(last);}
 else {const c={time:minute,open:price,high:price,low:price,close:price};candles.push(c);if(candles.length>1000)candles.shift();candleSeries.update(c);}
 $("lastPrice").textContent=price.toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:2});
}
function renderPositions(positions,quotes){
 $("positionsBody").innerHTML=positions.length?positions.map(p=>{const mark=quotes[p.symbol]?.price??p.entry;const pnl=(mark-p.entry)*p.quantity*(p.side==="BUY"?1:-1);return '<tr><td><b>'+escapeHtml(p.symbol)+'</b></td><td class="'+(p.side==="BUY"?"side-buy":"side-sell")+'">'+p.side+'</td><td>'+Number(p.quantity).toFixed(4)+'</td><td>'+Number(p.entry).toFixed(2)+'</td><td>'+Number(mark).toFixed(2)+'</td><td>'+(p.stop_loss==null?"—":Number(p.stop_loss).toFixed(2))+'</td><td>'+(p.take_profit==null?"—":Number(p.take_profit).toFixed(2))+'</td><td class="'+(pnl>=0?"good":"bad")+'">'+money(pnl)+'</td><td><button class="close" data-close="'+escapeHtml(p.id)+'">Close</button></td></tr>';}).join(""):'<tr><td colspan="9" class="empty">No open positions</td></tr>';
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
function paintRisk(risk){
 if(!risk)return;
 const locked=risk.status==="LOCKED";
 $("riskBadge").textContent=locked?"LOCKED":"ACTIVE";
 $("riskBadge").style.color=locked?"#ff6b7a":"#28d6a1";
 $("riskDaily").textContent=money(risk.daily_loss)+" / "+money(risk.daily_loss_limit);
 $("riskFloating").textContent=money(risk.floating_loss)+" / "+money(risk.floating_loss_limit);
 $("riskOpen").textContent=money(risk.open_risk)+" / "+money(risk.max_open_risk);
 $("riskFloor").textContent=money(risk.max_loss_floor);
 $("riskMessage").textContent=locked?"Trading locked: "+(risk.lock_reason||risk.reason)+". Manual reset/review is required; hard locks cannot be cleared by restarting.":"Active · "+risk.risk_per_trade_pct+"% risk/trade · "+risk.daily_loss_pct+"% internal daily stop · "+risk.max_drawdown_pct+"% static max-loss floor · UTC reset. Internal guardrails, not firm-certified.";
}
function paintAccount(account,quotes){
 paintRisk(account.risk);
 $("balance").textContent=money(account.balance);$("equity").textContent=money(account.equity);
 $("realized").textContent=money(account.realized_pnl);$("unrealized").textContent=money(account.unrealized_pnl);
 $("realized").className=account.realized_pnl>=0?"good":"bad";$("unrealized").className=account.unrealized_pnl>=0?"good":"bad";
 botRunning=!!account.auto;activeStrategyId=account.active_strategy||activeStrategyId;\n $("botStatus").textContent=account.auto?"● AUTO TRADING RUNNING · "+(account.active_timeframe||"1m"):"● AUTO TRADING STOPPED";
 $("autoBtn").disabled=account.auto;$("stopBtn").disabled=!account.auto;
 renderPositions(account.positions,quotes);renderHistory(account.history);
 $("positionCount").textContent=account.positions.length;$("historyCount").textContent=account.history.length;
}
async function refresh(){const [account,quotes]=await Promise.all([api("/api/account"),api("/api/quotes")]);paintAccount(account,quotes);return {account,quotes};}
function escapeHtml(value){return String(value??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
function renderStrategies(){
 const q=$("strategySearch").value.toLowerCase(),list=strategies.filter(s=>(s.name+" "+s.category).toLowerCase().includes(q));
 $("strategyCount").textContent=strategies.length;
 $("strategyList").innerHTML=list.map(s=>'<div class="strategy"><div><b>'+escapeHtml(s.name)+'</b><small>'+escapeHtml(s.category)+' · '+escapeHtml(s.rule_summary)+'</small></div><em>'+(s.executable?"IMPLEMENTED · PAPER":s.status==="research_required"?"RESEARCH ONLY":"TEMPLATE ONLY")+'</em></div>').join("");
}
async function loadStrategies(selected){strategies=await api("/api/strategies");const runnable=strategies.filter(s=>s.executable);$("autoStrategy").innerHTML=runnable.map(s=>'<option value="'+escapeHtml(s.id)+'">'+escapeHtml(s.name)+'</option>').join("");if(selected&&runnable.some(s=>s.id===selected))$("autoStrategy").value=selected;renderStrategies();}
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
$("autoBtn").onclick=async()=>{try{await api("/api/auto",{method:"POST",body:JSON.stringify({enabled:true,strategy_id:$("autoStrategy").value,risk_pct:Number($("risk").value),timeframe})});toast("Auto paper trading started");await refresh();}catch(e){toast(e.message);}};
$("stopBtn").onclick=async()=>{try{await api("/api/auto",{method:"POST",body:JSON.stringify({enabled:false,risk_pct:Number($("risk").value)})});toast("Auto trading stopped");await refresh();}catch(e){toast(e.message);}};
$("risk").oninput=()=>{$("riskLabel").textContent=Number($("risk").value).toFixed(2)+"%";};
$("strategySearch").oninput=renderStrategies;
$("saveCustom").onclick=async()=>{try{const body={name:$("customName").value,symbol:"BOTH",fast_ema:Number($("fastEma").value),slow_ema:Number($("slowEma").value),direction:"both"};const item=await api("/api/strategies/custom",{method:"POST",body:JSON.stringify(body)});strategies.push(item);await loadStrategies(item.id);toast("Custom EMA strategy saved and can be selected for paper automation");}catch(e){toast(e.message);}};
$("positionsBody").onclick=async event=>{const id=event.target.dataset.close;if(id){try{await api("/api/positions/"+id+"/close",{method:"POST"});toast("Position closed");await refresh();}catch(e){toast(e.message);}}};
async function switchSymbol(next){symbol=next;$("orderSymbol").value=symbol;document.querySelectorAll("[data-symbol]").forEach(b=>b.classList.toggle("active",b.dataset.symbol===symbol));$("chartTitle").textContent=symbol+(symbol==="XAUUSD"?" · Gold / US Dollar":" · Bitcoin / US Dollar");candles=[];candleSeries.setData([]);await loadCandles();}
document.querySelectorAll("[data-symbol]").forEach(button=>button.onclick=()=>switchSymbol(button.dataset.symbol).catch(e=>toast("Could not load "+symbol+": "+e.message)));
$("prevSymbol").onclick=()=>switchSymbol(symbol==="XAUUSD"?"BTCUSD":"XAUUSD").catch(e=>toast(e.message));
$("nextSymbol").onclick=()=>switchSymbol(symbol==="XAUUSD"?"BTCUSD":"XAUUSD").catch(e=>toast(e.message));
document.querySelectorAll("[data-timeframe]").forEach(button=>button.onclick=async()=>{timeframe=button.dataset.timeframe;document.querySelectorAll("[data-timeframe]").forEach(b=>b.classList.toggle("active",b===button));candles=[];candleSeries.setData([]);try{await loadCandles();if(botRunning){await api("/api/auto",{method:"POST",body:JSON.stringify({enabled:true,strategy_id:activeStrategyId,risk_pct:Number($("risk").value),timeframe})});toast("Bot timeframe changed to "+timeframe);}}catch(e){toast("Timeframe load failed: "+e.message);}});
$("showFvg").onchange=()=>window.drawTradeXZones?.();$("showOb").onchange=()=>window.drawTradeXZones?.();
$("zoomIn").onclick=()=>{chartBarSpacing=Math.min(30,chartBarSpacing*1.25);chart.timeScale().applyOptions({barSpacing:chartBarSpacing});};
$("zoomOut").onclick=()=>{chartBarSpacing=Math.max(2,chartBarSpacing/1.25);chart.timeScale().applyOptions({barSpacing:chartBarSpacing});};
$("restoreChart").onclick=()=>{chartBarSpacing=8;chart.timeScale().applyOptions({barSpacing:chartBarSpacing,rightOffset:5});chart.priceScale("right").applyOptions({autoScale:true});chart.timeScale().fitContent();};
async function boot(){await window.authReady;if(!await window.getTradeXAccessToken?.())return;initChart();const initial=await refresh();await loadStrategies(initial.account.active_strategy);await loadCandles().catch(()=>{});await refreshFeeds();connectMarketSocket();setInterval(refreshFeeds,30000);}
boot().catch(error=>toast(error.message));
