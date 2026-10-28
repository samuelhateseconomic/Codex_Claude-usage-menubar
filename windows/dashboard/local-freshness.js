// Status-only observation; never initiates imports, repricing or provider checks.
export function watchLocalPublication({client,document,window,onStatus,onFailure,intervalMs=30000}){
  let timer=null,request=null,generation=0,started=false,disposed=false;
  const visible=()=>document.visibilityState!=='hidden';
  function cancel(){generation++;if(timer!==null)window.clearTimeout(timer);timer=null;request?.abort();request=null;}
  function schedule(){if(started&&!disposed&&visible())timer=window.setTimeout(check,intervalMs);}
  async function check(){
    timer=null;if(disposed||!started||!visible())return;
    const current=generation,active=new AbortController();request=active;
    try{const status=await client.read('status',active.signal);if(!disposed&&current===generation&&!active.signal.aborted)onStatus(status);}
    catch(error){if(!disposed&&current===generation&&!active.signal.aborted)onFailure(error);}
    finally{if(current===generation){request=null;schedule();}}
  }
  function visibility(){cancel();if(started&&visible())void check();}
  document.addEventListener('visibilitychange',visibility);
  return {
    restart(){if(disposed)return;started=true;cancel();schedule();},
    dispose(){disposed=true;started=false;cancel();document.removeEventListener?.('visibilitychange',visibility);}
  };
}
