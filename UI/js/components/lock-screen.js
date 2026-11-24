function setLockedChromeState(locked){
const btnShrink=document.getElementById("btnShrink")
if(btnShrink)btnShrink.disabled=locked
// Terminal output is not read while locked (the bridge refuses it too); polling resumes after unlock.
if(typeof termSetLockPaused==="function")termSetLockPaused(locked)
}
let lockScreenToken=0
function showLockScreen(onUnlock){
const token=++lockScreenToken
const overlay=document.getElementById("lockOverlay")
const errEl=document.getElementById("lockError")
const titleEl=document.getElementById("lockTitle")
const subEl=document.getElementById("lockSubtitle")
const oldInput=document.getElementById("lockPinInput")
const input=oldInput.cloneNode(true)
oldInput.replaceWith(input)
const oldSubmit=document.getElementById("lockSubmitBtn")
const submit=oldSubmit.cloneNode(true)
oldSubmit.replaceWith(submit)
let done=false
function showError(msg){errEl.textContent=msg;errEl.classList.remove("hidden")}
function finish(){
if(done)return
done=true
overlay.classList.add("hidden")
setLockedChromeState(false)
input.value=""
onUnlock()
}
// Fail closed: the overlay goes up before we know anything, and only a successful status (no PIN) or a successful unlock takes it down.
overlay.classList.remove("hidden")
setLockedChromeState(true)
titleEl.textContent="LOYA NG is locked"
input.placeholder="Enter PIN"
submit.textContent="Unlock"
function attempt(){
if(done)return
const pin=input.value
errEl.classList.add("hidden")
submit.disabled=true
bridgeCall("security.unlock",[pin]).then(finish).catch((err)=>{
showError(err&&err.message?err.message:"Unlock failed")
input.value=""
input.focus()
}).finally(()=>{submit.disabled=false})
}
submit.addEventListener("click",attempt)
input.addEventListener("keydown",(e)=>{if(e.key==="Enter")attempt()})
input.focus()
function check(tries){
bridgeCall("security.status").then((st)=>{
if(done||token!==lockScreenToken)return
if(!st.pin_set){finish();return}
errEl.classList.add("hidden")
if(subEl)subEl.textContent=st.enc_enabled?"Enter your PIN to unlock the encrypted database.":"Enter your PIN to open LOYA NG."
if(st.lockout_seconds)showError(`Too many wrong PINs. Try again in ${st.lockout_seconds} second(s).`)
}).catch(()=>{
if(done||token!==lockScreenToken)return
showError("Could not read the lock state. Enter your PIN to continue.")
if(tries<5)setTimeout(()=>check(tries+1),1500)
})
}
check(0)
}
