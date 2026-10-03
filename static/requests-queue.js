document.addEventListener("DOMContentLoaded",()=>{
  if(!document.getElementById("requestsQueue"))return;
  const U=RequestUI,$=id=>document.getElementById(id);
  let page=1,selected=[],active=null;
  function basis(rec){
    const box=U.el("div");if(!rec){box.append(U.el("p","No saved recommendation yet. Select the request and calculate an allocation.","rq-note"));return box;}
    box.append(U.el("p",rec.explanation,"rq-note"));
    const table=U.el("table",null,"vp-tbl"),head=U.el("tr");
    ["Term","Quantity","Basis"].forEach(x=>head.append(U.el("th",x)));table.append(head);
    for(const [key,t] of Object.entries(rec.terms)){const tr=U.el("tr");[key,t.value==null?"Not available":t.value,t.basis||"Original request"].forEach(x=>tr.append(U.el("td",x)));table.append(tr);}
    box.append(table,U.el("p","Binding constraint: "+(rec.binding_terms.join(", ")||"No recommendation")+". Suggested grant: "+(rec.suggested_grant??"Officer review")+".","rq-note"));
    if(rec.unfunded_barangays?.length)box.append(U.el("p","Unfunded: "+rec.unfunded_barangays.map(x=>"#"+x.request_id+" "+x.barangay).join(", "),"rq-note"));
    if(rec.scenario)box.append(U.el("p","Saved "+rec.scenario.calculated_at+" by "+rec.scenario.calculated_by+"; request priority: "+rec.scenario.priority_order.join(", "),"rq-note"));
    return box;
  }
  function order(){
    $("rqPlan").replaceChildren();
    $("rqOrder").replaceChildren();
    selected.forEach((r,i)=>{
      const li=U.el("li");li.append(U.el("span",(i+1)+". #"+r.request_id+" "+r.barangay+" — "+r.qty_requested+" "+r.unit));
      for(const [label,delta] of [["↑",-1],["↓",1]]){const b=U.el("button",label,"secondary");b.type="button";b.setAttribute("aria-label","Move request "+r.request_id+(delta<0?" up":" down"));b.disabled=i+delta<0||i+delta>=selected.length;b.onclick=()=>{[selected[i],selected[i+delta]]=[selected[i+delta],selected[i]];order();};li.append(b);}
      const remove=U.el("button","Remove","secondary");remove.type="button";remove.onclick=()=>{selected.splice(i,1);order();load();};li.append(remove);$("rqOrder").append(li);
    });
  }
  async function load(){
    const query=new URLSearchParams({page});
    for(const [id,key] of [["rqStatus","status"],["rqBarangay","barangay"],["rqCategory","category"]])if($(id).value)query.set(key,$(id).value);
    try{
      const data=await U.api("/api/requests?"+query);$("rqRows").replaceChildren();
      for(const r of data.items){
        const tr=U.el("tr"),td=U.el("td"),check=U.el("input");check.type="checkbox";check.setAttribute("aria-label","Select request "+r.request_id);check.checked=selected.some(x=>x.request_id===r.request_id);
        check.onchange=()=>{selected=selected.filter(x=>x.request_id!==r.request_id);if(check.checked)selected.push(r);order();$("rqAllocation").open=true;};td.append(check);tr.append(td);
        for(const text of ["#"+r.request_id+" / "+r.request_date,r.barangay,r.category+" / "+r.unit,r.qty_requested,r.qty_recommended==null?"Not assessed":r.qty_recommended,r.qty_granted==null?"Pending":r.qty_granted,r.status+" / "+r.source])tr.append(U.el("td",text));
        const action=U.el("td"),btn=U.el("button","Review","secondary");btn.type="button";btn.onclick=()=>openDecision(r.request_id);action.append(btn);tr.append(action);$("rqRows").append(tr);
      }
      if(!data.items.length){const tr=U.el("tr"),td=U.el("td","No requests match these filters.");td.colSpan=9;tr.append(td);$("rqRows").append(tr);}
      $("rqPage").textContent="Page "+page+" · "+data.total+" requests";$("rqPrev").disabled=page<=1;$("rqNext").disabled=page*20>=data.total;
      const summary=await U.api("/api/requests/summary");
      const pending=summary.groups.filter(x=>["SUBMITTED","UNDER_REVIEW"].includes(x.status)).reduce((n,x)=>n+x.count,0);
      $("queueSummary").textContent=pending+" awaiting review · "+summary.total+" total requests";
      const chain=$("rqChainRows");chain.replaceChildren();
      for(const c of summary.chain||[]){const tr=U.el("tr"),pct=v=>v==null?"Not yet":v+"%";
        for(const text of [c.category+" / "+c.unit,c.requests,c.requested,c.assessed_requested?c.recommended:"—",c.decided_requested?c.granted:"—",pct(c.recommended_pct_of_assessed),pct(c.granted_pct_of_decided)])tr.append(U.el("td",text));chain.append(tr);}
      if(!(summary.chain||[]).length){const tr=U.el("tr"),td=U.el("td","No requests yet.");td.colSpan=7;tr.append(td);chain.append(tr);}
    }catch(e){U.message("rqMessage",e.message,true);}
  }
  async function openDecision(id){
    try{
      active=await U.api("/api/requests/"+id);const form=$("rqDecision");
      $("rqDecisionTitle").textContent="Request #"+id+" · "+active.barangay;
      $("rqDetail").replaceChildren(U.el("p",active.category+" · "+(active.item||"No item specified")+" · requested "+active.qty_requested+" "+active.unit,"rq-note"),
        U.el("p","Source: "+active.source+" · requested by "+(active.requested_by||"—")+" · contact "+(active.contact_no||"—"),"rq-note"));
      const doc=U.el("a","View request document");doc.href="/request/"+id+"/document";doc.target="_blank";doc.rel="noopener";
      $("rqDetail").append(U.el("p","Approving or partly approving signs this document with your profile signature and the date; declining cancels it. ","rq-note"));
      $("rqDetail").lastChild.append(doc);
      $("rqBasis").replaceChildren(basis(active.recommendation));
      form.elements.status.value=active.status==="SUBMITTED"?(active.recommendation?.suggested_status||"UNDER_REVIEW"):active.status;
      form.elements.qty_granted.value=active.qty_granted??active.recommendation?.suggested_grant??0;
      form.elements.qty_granted.max=active.qty_requested;
      form.elements.session_id.value=active.session_id??"";
      form.elements.decision_note.value=active.decision_note||"";form.elements.override.checked=false;
      U.message("rqDecisionMessage","");$("rqDialog").showModal();
    }catch(e){U.message("rqMessage",e.message,true);}
  }
  $("rqClose").onclick=()=>$("rqDialog").close();
  $("rqDecision").addEventListener("submit",async e=>{
    e.preventDefault();const form=e.currentTarget,b=form.elements;$("rqSave").disabled=true;
    try{
      await U.api("/api/requests/"+active.request_id+"/decide?override="+b.override.checked,U.json({
        status:b.status.value,qty_granted:Number(b.qty_granted.value),decision_note:b.decision_note.value||null,session_id:b.session_id.value?Number(b.session_id.value):null
      }));
      selected=selected.filter(r=>r.request_id!==active.request_id);order();$("rqDialog").close();U.message("rqMessage","Decision saved for request #"+active.request_id+".");await load();
    }catch(err){U.message("rqDecisionMessage",err.message,true);}finally{$("rqSave").disabled=false;}
  });
  $("rqCalculate").onclick=async()=>{
    if(!selected.length){U.message("rqMessage","Select pending requests first.",true);return;}
    if($("rqAvailable").value===""||!$("rqAvailable").checkValidity()){U.message("rqMessage","Enter a nonnegative whole number of available vials.",true);return;}
    $("rqCalculate").disabled=true;
    try{
      const plan=await U.api("/api/requests/allocation",U.json({request_ids:selected.map(r=>r.request_id),vials_available:Number($("rqAvailable").value),service_level:Number($("rqLevel").value)}));
      $("rqPlan").replaceChildren(U.el("p",plan.vials_committed+" vials planned · "+plan.vials_remaining+" remain · "+plan.unfunded.length+" requests unfunded.","rq-note"));
      for(const r of plan.recommendations){const d=U.el("details");d.append(U.el("summary","#"+r.request_id+" "+r.barangay+" · recommended "+(r.recommended??"not available")));d.append(basis(r));$("rqPlan").append(d);}
      U.message("rqMessage","Recommendations saved. Each grant still requires an officer decision.");await load();
    }catch(e){U.message("rqMessage",e.message,true);}finally{$("rqCalculate").disabled=false;}
  };
  $("rqLetter").onclick=async()=>{
    if(!selected.length){U.message("rqMessage","Select anti-rabies requests first.",true);return;}
    try{
      const r=await fetch("/api/requests/letter?request_ids="+selected.map(x=>x.request_id).join(","));
      if(!r.ok){const d=await r.json();throw Error(d.detail||"Letter could not be generated.");}
      const url=URL.createObjectURL(await r.blob()),a=U.el("a");a.href=url;a.download="vaccine_request_letter.docx";a.click();setTimeout(()=>URL.revokeObjectURL(url),5000);
      U.message("rqMessage","Letter generated using quantities requested, not quantities granted.");
    }catch(e){U.message("rqMessage",e.message,true);}
  };
  $("rqClear").onclick=()=>{selected=[];order();load();};
  ["rqStatus","rqBarangay","rqCategory"].forEach(id=>$(id).onchange=()=>{page=1;load();});
  $("rqPrev").onclick=()=>{page--;load();};$("rqNext").onclick=()=>{page++;load();};$("rqRefresh").onclick=load;
  U.api("/api/planner/barangays").then(data=>{data.barangays.forEach(n=>{const o=U.el("option",n);o.value=n;$("rqBarangay").append(o);});}).catch(e=>U.message("rqMessage",e.message,true));
  load();
});
