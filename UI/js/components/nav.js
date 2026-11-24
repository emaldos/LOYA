function initNav(){
const nav=document.getElementById("bottomNav")
// Only page buttons navigate; the Terminal button in the dock is a panel toggle (wired in terminal.js).
const buttons=nav.querySelectorAll(".nav-btn[data-page]")
let hideTimer=null
nav.addEventListener("mouseenter",()=>{
if(hideTimer)clearTimeout(hideTimer)
nav.classList.add("expanded")
})
nav.addEventListener("mouseleave",()=>{
hideTimer=setTimeout(()=>nav.classList.remove("expanded"),140)
})
buttons.forEach((btn)=>{
btn.addEventListener("click",()=>goToPage(btn.dataset.page))
})
}
