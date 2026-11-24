function sizeSwatchShape(size){
return `<span class="dash-size-swatch-shape" data-size="${size}"></span>`
}
function renderSizePicker(sizes,currentSize,onPick,labels){
const wrap=document.createElement("div")
wrap.className="dash-size-grid"
wrap.setAttribute("role","group")
wrap.setAttribute("aria-label","Card size")
sizes.forEach((size)=>{
const btn=document.createElement("button")
btn.type="button"
btn.className="dash-size-swatch"+(size===currentSize?" active":"")
const label=(labels&&labels[size])||size
btn.title=label
btn.setAttribute("aria-label","Size: "+label)
btn.setAttribute("aria-pressed",size===currentSize?"true":"false")
btn.innerHTML=sizeSwatchShape(size)
btn.addEventListener("click",()=>onPick(size))
wrap.appendChild(btn)
})
return wrap
}
