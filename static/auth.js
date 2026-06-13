/* Εστία — κοινό «νευρωνικό» πλέγμα για τις pre-login οθόνες (login, εγγραφή) */
(function(){
  var c=document.getElementById('bg'); if(!c) return;
  var x=c.getContext('2d'), W,H,DPR=Math.min(window.devicePixelRatio||1,2), pts=[];
  function size(){ W=c.width=innerWidth*DPR; H=c.height=innerHeight*DPR; c.style.width=innerWidth+'px'; c.style.height=innerHeight+'px'; }
  size(); addEventListener('resize', size);
  var N=Math.min(90, Math.round(innerWidth*innerHeight/16000));
  for(var i=0;i<N;i++){ pts.push({x:Math.random()*W,y:Math.random()*H,vx:(Math.random()-.5)*.25*DPR,vy:(Math.random()-.5)*.25*DPR}); }
  var LINK=140*DPR;
  function frame(){
    x.clearRect(0,0,W,H);
    for(var i=0;i<pts.length;i++){ var p=pts[i]; p.x+=p.vx; p.y+=p.vy; if(p.x<0||p.x>W) p.vx*=-1; if(p.y<0||p.y>H) p.vy*=-1; }
    for(var i=0;i<pts.length;i++){ for(var j=i+1;j<pts.length;j++){ var a=pts[i], b=pts[j], dx=a.x-b.x, dy=a.y-b.y, d=Math.sqrt(dx*dx+dy*dy);
      if(d<LINK){ var o=(1-d/LINK)*.5; x.strokeStyle='rgba(56,189,248,'+o.toFixed(3)+')'; x.lineWidth=DPR; x.beginPath(); x.moveTo(a.x,a.y); x.lineTo(b.x,b.y); x.stroke(); } } }
    for(var i=0;i<pts.length;i++){ var p=pts[i]; x.fillStyle='rgba(125,220,250,.85)'; x.beginPath(); x.arc(p.x,p.y,1.7*DPR,0,6.2832); x.fill(); }
    requestAnimationFrame(frame);
  }
  frame();
})();
/* language popover + toast (placeholder OAuth) */
function authToggleLang(e){ if(e) e.stopPropagation(); var b=document.getElementById('langbar'); if(b) b.classList.toggle('open'); }
document.addEventListener('click', function(e){ var b=document.getElementById('langbar'); if(b && !b.contains(e.target)) b.classList.remove('open'); });
function authSoon(name){
  var t=document.getElementById('toast'); if(!t) return;
  t.textContent=name+' — σύντομα διαθέσιμο';
  t.classList.add('show'); clearTimeout(window.__at); window.__at=setTimeout(function(){ t.classList.remove('show'); }, 2400);
}
