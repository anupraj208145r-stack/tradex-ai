(function(){
 const $=id=>document.getElementById(id);
 const showError=msg=>{const el=$("authError");el.textContent=msg||"";el.style.display=msg?"block":"none";};
 const validConfig=()=>window.TRADEX_SUPABASE_URL&&!window.TRADEX_SUPABASE_URL.includes("YOUR_PROJECT")&&window.TRADEX_SUPABASE_ANON_KEY&&!window.TRADEX_SUPABASE_ANON_KEY.includes("YOUR_SUPABASE");
 let client=null,phonePending=null,recoveryMode=false,phoneVerified=false,phoneSetupPending=false;
 window.authReady=(async()=>{
  if(!window.supabase||!validConfig()){showError("Setup needed: add your Supabase Project URL and publishable/anon key in frontend/supabase-config.js.");return null;}
  client=window.supabase.createClient(window.TRADEX_SUPABASE_URL,window.TRADEX_SUPABASE_ANON_KEY,{auth:{persistSession:true,autoRefreshToken:true,detectSessionInUrl:true}});
  window.tradeXAuth=client;
  const {data:{session}}=await client.auth.getSession();
  if(session){$("authGate").style.display="none";document.querySelector(".app").style.display="grid";$("userEmail").textContent=session.user.email||session.user.phone||"Signed in";}
  else{document.querySelector(".app").style.display="none";$("authGate").style.display="grid";}
  client.auth.onAuthStateChange((event,session)=>{
   if(session&&!phoneSetupPending){$("authGate").style.display="none";document.querySelector(".app").style.display="grid";$("userEmail").textContent=session.user.email||session.user.phone||"Signed in";}
   else if(!session){document.querySelector(".app").style.display="none";$("authGate").style.display="grid";}
  });
  if(location.hash.includes("type=recovery")){ recoveryMode=true;$("authGate").style.display="grid";document.querySelector(".app").style.display="none";$("authPassword").placeholder="Enter new password";$("forgotPassword").textContent="Update password";$("forgotPassword").dataset.recovery="1";}
  return client;
 })();
 async function run(action){showError("");try{if(!client)throw new Error("Supabase is not configured yet.");const result=await action();if(result&&result.error)throw result.error;}catch(e){showError(e.message||"Authentication failed. Please try again.");}}
 $("emailLogin").onclick=()=>run(async()=>{const r=await client.auth.signInWithPassword({email:$("authEmail").value.trim(),password:$("authPassword").value});if(!r.error)location.reload();return r;});
 $("emailSignup").onclick=()=>run(async()=>{const r=await client.auth.signUp({email:$("authEmail").value.trim(),password:$("authPassword").value,options:{emailRedirectTo:location.origin}});if(!r.error&&r.data.session)location.reload();else if(!r.error)showError("Check your email to confirm your account, then sign in.");return r;});
 $("googleLogin").onclick=()=>run(()=>client.auth.signInWithOAuth({provider:"google",options:{redirectTo:location.origin}}));
 $("forgotPassword").onclick=()=>run(async()=>{
  if($("forgotPassword").dataset.recovery==="1"){const password=$("authPassword").value;if(password.length<8)throw new Error("Password must contain at least 8 characters.");const r=await client.auth.updateUser({password});if(!r.error){showError("Password updated successfully.");$("forgotPassword").dataset.recovery="";recoveryMode=false;setTimeout(()=>location.reload(),700);}return r;}
  const email=$("authEmail").value.trim();if(!email)throw new Error("Enter your email address first.");const r=await client.auth.resetPasswordForEmail(email,{redirectTo:location.origin});if(!r.error)showError("Password reset link sent. Check your email.");return r;
 });
 $("sendOtp").onclick=()=>run(async()=>{const phone=$("authPhone").value.trim();if(!/^\+[1-9][0-9]{7,14}$/.test(phone))throw new Error("Use international phone format, for example +919876543210.");const r=await client.auth.signInWithOtp({phone,options:{shouldCreateUser:true}});if(!r.error){phonePending=phone;phoneVerified=false;$("otpArea").hidden=false;$("savePhonePassword").hidden=true;showError("OTP sent by SMS. Enter it below.");}return r;});
 $("verifyOtp").onclick=()=>run(async()=>{if(!phonePending)throw new Error("Request an OTP first.");phoneSetupPending=true;const r=await client.auth.verifyOtp({phone:phonePending,token:$("authOtp").value.trim(),type:"sms"});if(r.error){phoneSetupPending=false;throw r.error;}phoneVerified=true;$("savePhonePassword").hidden=false;showError("Phone verified. Enter your new password above and select Set / reset phone password.");});
 $("savePhonePassword").onclick=()=>run(async()=>{if(!phoneVerified)throw new Error("Verify your phone OTP first.");const password=$("authPassword").value;if(password.length<8)throw new Error("Password must contain at least 8 characters.");const r=await client.auth.updateUser({password});if(r.error)throw r.error;showError("Phone password saved. You can now sign in using your phone and OTP.");phoneSetupPending=false;setTimeout(()=>location.reload(),700);});
 $("logoutBtn").onclick=()=>run(()=>client.auth.signOut());
 window.getTradeXAccessToken=async()=>{const c=client||await window.authReady;if(!c||recoveryMode)return null;const {data:{session}}=await c.auth.getSession();return session?session.access_token:null;};
})();