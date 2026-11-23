(function(){
 const $=id=>document.getElementById(id);
 const isLogin=!!$("authGate"),isDashboard=document.body.dataset.page==="dashboard";
 const showError=msg=>{const el=$("authError");if(el){el.textContent=msg||"";el.style.display=msg?"block":"none";}};
 const validConfig=()=>window.TRADEX_SUPABASE_URL&&!window.TRADEX_SUPABASE_URL.includes("YOUR_PROJECT")&&window.TRADEX_SUPABASE_ANON_KEY&&!window.TRADEX_SUPABASE_ANON_KEY.includes("YOUR_SUPABASE");
 let client=null,phonePending=null,phoneVerified=false;
 async function syncServerSession(session){
  if(!session?.access_token)throw new Error("No active sign-in session was found.");
  const response=await fetch("/auth/session",{method:"POST",headers:{Authorization:"Bearer "+session.access_token}});
  if(!response.ok){let detail="Could not establish the secure app session.";try{detail=(await response.json()).detail||detail;}catch{}throw new Error(detail);}
 }
 window.authReady=(async()=>{
  if(!window.supabase||!validConfig()){if(isLogin)showError("Supabase setup is incomplete. Please contact support.");if(isDashboard)location.replace("/login");return null;}
  client=window.supabase.createClient(window.TRADEX_SUPABASE_URL,window.TRADEX_SUPABASE_ANON_KEY,{auth:{persistSession:true,autoRefreshToken:true,detectSessionInUrl:true}});
  window.tradeXAuth=client;
  const {data:{session}}=await client.auth.getSession();
  if(isLogin&&session){try{await syncServerSession(session);location.replace("/dashboard");}catch(e){showError(e.message);}}
  if(isDashboard){
   if(!session){location.replace("/login");return null;}
   try{await syncServerSession(session);}catch(e){await client.auth.signOut();location.replace("/login");return null;}
   const user=$("userEmail");if(user)user.textContent=session.user.email||session.user.phone||"Signed in";
  }
  client.auth.onAuthStateChange((event)=>{if(event==="SIGNED_OUT"&&isDashboard)location.replace("/login");});
  return client;
 })();
 async function finishLogin(){const {data:{session}}=await client.auth.getSession();await syncServerSession(session);location.assign("/dashboard");}
 async function run(action){showError("");try{if(!client)throw new Error("Authentication is not ready. Refresh and try again.");const result=await action();if(result?.error)throw result.error;}catch(e){showError(e.message||"Authentication failed. Please try again.");}}
 if(isLogin){
  const recovery=location.hash.includes("type=recovery");
  if(recovery){$("authPassword").placeholder="Enter new password";$("forgotPassword").textContent="Update password";}
  $("emailLogin").onclick=()=>run(async()=>{const r=await client.auth.signInWithPassword({email:$("authEmail").value.trim(),password:$("authPassword").value});if(!r.error)await finishLogin();return r;});
  $("emailSignup").onclick=()=>run(async()=>{const r=await client.auth.signUp({email:$("authEmail").value.trim(),password:$("authPassword").value,options:{emailRedirectTo:location.origin+"/login"}});if(r.error)throw r.error;if(r.data.session)await finishLogin();else showError("Check your email to confirm your account, then sign in.");});
  $("googleLogin").onclick=()=>run(()=>client.auth.signInWithOAuth({provider:"google",options:{redirectTo:location.origin+"/login"}}));
  $("forgotPassword").onclick=()=>run(async()=>{if(recovery){const password=$("authPassword").value;if(password.length<8)throw new Error("Password must contain at least 8 characters.");const r=await client.auth.updateUser({password});if(!r.error){showError("Password updated. Please sign in.");history.replaceState(null,"",location.pathname);$("forgotPassword").textContent="Forgot password?";$("authPassword").value="";}return r;}const email=$("authEmail").value.trim();if(!email)throw new Error("Enter your email address first.");const r=await client.auth.resetPasswordForEmail(email,{redirectTo:location.origin+"/login"});if(!r.error)showError("Password reset link sent. Check your email.");return r;});
  $("sendOtp").onclick=()=>run(async()=>{const phone=$("authPhone").value.trim();if(!/^\+[1-9][0-9]{7,14}$/.test(phone))throw new Error("Use international phone format, for example +919876543210.");const r=await client.auth.signInWithOtp({phone,options:{shouldCreateUser:true}});if(!r.error){phonePending=phone;phoneVerified=false;$("otpArea").hidden=false;$("savePhonePassword").hidden=true;$("continuePhone").hidden=true;showError("OTP sent by SMS. Enter it below.");}return r;});
  $("verifyOtp").onclick=()=>run(async()=>{if(!phonePending)throw new Error("Request an OTP first.");const r=await client.auth.verifyOtp({phone:phonePending,token:$("authOtp").value.trim(),type:"sms"});if(r.error)throw r.error;phoneVerified=true;$("savePhonePassword").hidden=false;$("continuePhone").hidden=false;showError("Phone verified. Set a password or continue with OTP login.");});
  $("savePhonePassword").onclick=()=>run(async()=>{if(!phoneVerified)throw new Error("Verify your phone OTP first.");const password=$("authPassword").value;if(password.length<8)throw new Error("Password must contain at least 8 characters.");const r=await client.auth.updateUser({password});if(r.error)throw r.error;await finishLogin();});
  $("continuePhone").onclick=()=>run(async()=>{if(!phoneVerified)throw new Error("Verify your phone OTP first.");await finishLogin();});
 }
 if(isDashboard&&$("logoutBtn"))$("logoutBtn").onclick=async()=>{try{await client.auth.signOut();await fetch("/auth/logout",{method:"POST"});}finally{location.assign("/");}};
 window.getTradeXAccessToken=async()=>{const c=client||await window.authReady;if(!c)return null;const {data:{session}}=await c.auth.getSession();return session?session.access_token:null;};
})();