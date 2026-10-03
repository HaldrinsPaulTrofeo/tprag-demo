document.addEventListener("DOMContentLoaded", async () => {
  const U=RequestUI, form=document.getElementById("requestForm");
  if(!form)return;
  let me, profile=null, page=1;
  function docLink(id){const a=U.el("a","Open");a.href="/request/"+id+"/document";return a;}
  function preview(){
    const target=document.getElementById("letterPreview");if(!target||!window.RequestLetter)return;
    const v=n=>field(n).value;
    const num=n=>v(n)===""?null:Number(v(n));
    const brgy=me&&me.role==="barangay"?me.barangay:v("barangay");
    RequestLetter.render({barangay:brgy,category:v("category"),item:v("item")||null,unit:v("unit"),
      qty_requested:num("qty_requested"),animals_estimated:num("animals_estimated"),households_estimated:num("households_estimated"),
      request_date:v("request_date"),needed_by:v("needed_by")||null,contact_no:v("contact_no")||null,
      requested_by:v("requested_by")||null,source:field("source").value,state:"pending",
      seal:profile&&profile.seal,
      requester:profile&&profile.complete?{name:profile.profile_name,position:profile.profile_position,signature:profile.signature,signed_at:null}:null},
      target,{preview:true});
  }
  form.addEventListener("input",preview);form.addEventListener("change",preview);
  const field=n=>form.elements.namedItem(n);
  const now=new Date(), today=[now.getFullYear(),String(now.getMonth()+1).padStart(2,"0"),String(now.getDate()).padStart(2,"0")].join("-");
  field("request_date").value=today;field("request_date").max=today;
  async function loadMine(){
    try {
      const data=await U.api("/api/requests/mine?page="+page), rows=document.getElementById("mineRows");
      rows.replaceChildren();
      for(const r of data.items){
        const tr=U.el("tr");
        for(const text of [r.request_id+" / "+r.request_date,r.category+" / "+(r.item||"—"),
          r.qty_requested+" "+r.unit,r.qty_recommended==null?"Not assessed":r.qty_recommended,
          r.qty_granted==null?"Pending":r.qty_granted,r.status+"\n"+(r.decision_note||"")])tr.append(U.el("td",text));
        const d=U.el("td");d.append(docLink(r.request_id));tr.append(d);
        rows.append(tr);
      }
      if(!data.items.length){const tr=U.el("tr"),td=U.el("td","No requests yet.");td.colSpan=7;tr.append(td);rows.append(tr);}
      document.getElementById("minePage").textContent="Page "+page+" · "+data.total+" requests";
      document.getElementById("minePrev").disabled=page<=1;
      document.getElementById("mineNext").disabled=page*20>=data.total;
      U.message("mineMessage","");
    }catch(e){U.message("mineMessage",e.message,true);}
  }
  field("category").addEventListener("change",()=>{
    const anti=field("category").value==="ANTI_RABIES";
    field("unit").readOnly=anti;field("unit").value=anti?"vials":({SEEDS:"bags",FINGERLINGS:"pieces",LIVESTOCK:"heads"}[field("category").value]||"units");
    document.getElementById("categoryNote").textContent=anti?"Anti-rabies recommendations use recorded vaccination sessions.":"This category is recorded for officer review. No service history is available to support an automated recommendation.";
  });
  form.addEventListener("submit",async e=>{
    e.preventDefault();if(!me)return;
    const button=document.getElementById("submitRequest");button.disabled=true;
    const body=Object.fromEntries(new FormData(form));
    if(me.role==="barangay")body.barangay=me.barangay;
    for(const key of ["qty_requested","animals_estimated","households_estimated"])body[key]=body[key]===""?null:Number(body[key]);
    for(const key of ["needed_by","item","requested_by","contact_no"])if(!body[key])body[key]=null;
    try{
      const r=await U.api("/api/requests",U.json(body));
      U.message("requestMessage","Request #"+r.request_id+" submitted and signed. Status: "+r.status+". ");
      document.getElementById("requestMessage").append(docLink(r.request_id));
      field("qty_requested").value="";field("item").value="";
      if(me.role==="barangay"){page=1;await loadMine();}
    }catch(err){U.message("requestMessage",err.message,true);}finally{button.disabled=false;}
  });
  document.getElementById("minePrev").onclick=()=>{page--;loadMine();};
  document.getElementById("mineNext").onclick=()=>{page++;loadMine();};
  document.getElementById("refreshMine").onclick=loadMine;
  try{
    let choices; [me,choices]=await Promise.all([U.api("/api/me"),U.api("/api/planner/barangays")]);
    for(const name of choices.barangays){const o=U.el("option",name);o.value=name;field("barangay").append(o);}
    if(me.role==="barangay"){
      field("barangay").value=me.barangay;field("barangay").disabled=true;document.getElementById("myRequests").hidden=false;
      profile=await U.api("/api/profile");
      document.getElementById("signNote").hidden=!profile.complete;
      if(!profile.complete){
        const gate=document.getElementById("profileGate"),link=U.el("a","Complete your profile");link.href="/account#profile";
        gate.textContent="Before submitting, set up your signatory profile: printed name, position and signature. ";gate.append(link);gate.hidden=false;
        document.getElementById("submitRequest").disabled=true;
      }
      await loadMine();
    }
    else {
      // Staff do not request from barangays: this form records a request a
      // barangay delivered on paper, in person or by phone, into the same queue.
      document.getElementById("sourceField").hidden=false;
      field("source").value="letter";
      field("source").options[0].textContent="Walk-in or phone request taken by staff";
      document.getElementById("requestTitle").textContent="Encode a barangay’s request";
      document.getElementById("requestIntro").textContent="Record a request a barangay sent as a paper letter, or made in person or by phone, so it joins the same queue, allocation and decision record as online requests. Choose the barangay that made the request.";
      document.getElementById("previewTitle").textContent="Preview of the encoded request";
      document.getElementById("previewIntro").textContent="How this request will appear in the barangay’s request document. Paper letters keep the original signed copy on file; this record has no e-signature.";
      field("requested_by").placeholder="Signatory on the letter, e.g. Punong Barangay";
    }
    preview();
  }catch(e){U.message("requestMessage",e.message,true);document.getElementById("submitRequest").disabled=true;}
});
