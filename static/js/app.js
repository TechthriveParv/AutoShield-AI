(() => {
 const root=document.documentElement, saved=localStorage.getItem("autoshield-theme"); if(saved) root.dataset.theme=saved;
 const toggle=document.getElementById("theme-toggle"); if(toggle) toggle.onclick=()=>{root.dataset.theme=root.dataset.theme==="dark"?"light":"dark";localStorage.setItem("autoshield-theme",root.dataset.theme);if(window.DASH||window.ANALYTICS)location.reload()};
 const colors=["#42d9f5","#ff5267","#8b7bff","#f6b84a","#54d6a1","#f78cdb","#8aa8ff"];
 Chart.defaults.color=getComputedStyle(root).getPropertyValue("--muted").trim()||"#93a5bf";
 Chart.defaults.borderColor=getComputedStyle(root).getPropertyValue("--border").trim()||"#24344c";
 const common={responsive:true,maintainAspectRatio:false,plugins:{legend:{labels:{usePointStyle:true,boxWidth:8,padding:16}}}};
 function bar(id,rows,horizontal=false){let e=document.getElementById(id);if(!e)return;new Chart(e,{type:"bar",data:{labels:rows.map(x=>x.label),datasets:[{data:rows.map(x=>x.n),backgroundColor:rows.map((_,i)=>colors[i%colors.length]),borderRadius:5,borderSkipped:false}]},options:{...common,indexAxis:horizontal?"y":"x",plugins:{legend:{display:false}},scales:{x:{beginAtZero:true,ticks:{precision:0}},y:{beginAtZero:true,ticks:{precision:0}}}}})}
 function donut(id,rows){let e=document.getElementById(id);if(!e)return;new Chart(e,{type:"doughnut",data:{labels:rows.map(x=>x.label),datasets:[{data:rows.map(x=>x.n),backgroundColor:colors,borderWidth:0}]},options:{...common,cutout:"68%",plugins:{legend:{position:"bottom",labels:{usePointStyle:true,boxWidth:8}}}}})}
 if(window.DASH){donut("typeChart",window.DASH.types||[])}
 if(window.ANALYTICS){bar("kindChart",window.ANALYTICS.kinds,true);donut("reviewChart",window.ANALYTICS.statuses);bar("monthChart",window.ANALYTICS.months);bar("makeChart",window.ANALYTICS.makes,true)}
})();