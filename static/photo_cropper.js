
(function(){
  'use strict';

  function init(){
    const input=document.getElementById('photo_input');
    const hidden=document.getElementById('cropped_photo');
    const wrap=document.getElementById('cropper_wrap');
    const canvas=document.getElementById('crop_canvas');
    const zoom=document.getElementById('crop_zoom');
    const confirmBtn=document.getElementById('crop_confirm_btn');
    const resetBtn=document.getElementById('crop_reset_btn');
    const status=document.getElementById('crop_status');
    const previewWrap=document.getElementById('cropped_preview_wrap');
    const preview=document.getElementById('cropped_preview');
    const form=document.getElementById('candidateForm');

    if(!input || !hidden || !wrap || !canvas || !zoom || !confirmBtn || !form){
      return;
    }

    const ctx=canvas.getContext('2d');
    let img=null;
    let baseScale=1;
    let scale=1;
    let x=0, y=0;
    let dragging=false;
    let startX=0, startY=0;

    function clamp(){
      if(!img) return;
      const w=img.naturalWidth*scale;
      const h=img.naturalHeight*scale;
      const minX=canvas.width-w;
      const minY=canvas.height-h;
      x=Math.max(minX,Math.min(0,x));
      y=Math.max(minY,Math.min(0,y));
    }

    function draw(){
      if(!img) return;
      clamp();
      ctx.clearRect(0,0,canvas.width,canvas.height);
      ctx.fillStyle='#ddd';
      ctx.fillRect(0,0,canvas.width,canvas.height);
      ctx.drawImage(img,x,y,img.naturalWidth*scale,img.naturalHeight*scale);

      // visible crop border
      ctx.save();
      ctx.strokeStyle='rgba(255,255,255,.95)';
      ctx.lineWidth=6;
      ctx.strokeRect(3,3,canvas.width-6,canvas.height-6);
      ctx.restore();
    }

    function reset(){
      if(!img) return;
      baseScale=Math.max(canvas.width/img.naturalWidth,canvas.height/img.naturalHeight);
      zoom.value='1';
      scale=baseScale;
      x=(canvas.width-img.naturalWidth*scale)/2;
      y=(canvas.height-img.naturalHeight*scale)/2;
      hidden.value='';
      previewWrap.hidden=true;
      status.className='lookup-status lookup-working';
      status.textContent='Drag to reposition. Adjust Zoom, then click “Crop & Use Photo”.';
      draw();
    }

    function pos(ev){
      const r=canvas.getBoundingClientRect();
      const point=ev.touches ? ev.touches[0] : ev;
      return {
        x:(point.clientX-r.left)*(canvas.width/r.width),
        y:(point.clientY-r.top)*(canvas.height/r.height)
      };
    }

    input.addEventListener('change',function(){
      hidden.value='';
      previewWrap.hidden=true;
      const file=input.files && input.files[0];
      if(!file){
        wrap.hidden=true;
        return;
      }
      if(!file.type.startsWith('image/')){
        wrap.hidden=false;
        status.className='lookup-status lookup-error';
        status.textContent='Please choose a JPG, PNG or other image file.';
        return;
      }

      const reader=new FileReader();
      reader.onerror=function(){
        wrap.hidden=false;
        status.className='lookup-status lookup-error';
        status.textContent='The selected photo could not be read.';
      };
      reader.onload=function(e){
        const loaded=new Image();
        loaded.onload=function(){
          img=loaded;
          wrap.hidden=false;
          reset();
          setTimeout(()=>wrap.scrollIntoView({behavior:'smooth',block:'center'}),50);
        };
        loaded.onerror=function(){
          wrap.hidden=false;
          status.className='lookup-status lookup-error';
          status.textContent='The selected image format could not be opened.';
        };
        loaded.src=e.target.result;
      };
      reader.readAsDataURL(file);
    });

    zoom.addEventListener('input',function(){
      if(!img) return;
      const oldScale=scale;
      const centerX=(canvas.width/2-x)/oldScale;
      const centerY=(canvas.height/2-y)/oldScale;
      scale=baseScale*parseFloat(zoom.value);
      x=canvas.width/2-centerX*scale;
      y=canvas.height/2-centerY*scale;
      hidden.value='';
      previewWrap.hidden=true;
      draw();
    });

    resetBtn.addEventListener('click',reset);

    function begin(ev){
      if(!img) return;
      dragging=true;
      const p=pos(ev);
      startX=p.x-x;
      startY=p.y-y;
      ev.preventDefault();
    }
    function move(ev){
      if(!dragging || !img) return;
      const p=pos(ev);
      x=p.x-startX;
      y=p.y-startY;
      hidden.value='';
      previewWrap.hidden=true;
      draw();
      ev.preventDefault();
    }
    function finish(){ dragging=false; }

    canvas.addEventListener('mousedown',begin);
    canvas.addEventListener('mousemove',move);
    window.addEventListener('mouseup',finish);
    canvas.addEventListener('touchstart',begin,{passive:false});
    canvas.addEventListener('touchmove',move,{passive:false});
    window.addEventListener('touchend',finish);

    confirmBtn.addEventListener('click',function(){
      if(!img){
        status.className='lookup-status lookup-error';
        status.textContent='Select a photo first.';
        return;
      }
      draw();
      const result=canvas.toDataURL('image/jpeg',0.88);
      hidden.value=result;
      preview.src=result;
      previewWrap.hidden=false;
      status.className='lookup-status lookup-success';
      status.textContent='✓ Crop confirmed. The preview below is the exact photo that will be saved.';
      previewWrap.scrollIntoView({behavior:'smooth',block:'center'});
    });

    form.addEventListener('submit',function(ev){
      if(input.files && input.files.length && !hidden.value){
        ev.preventDefault();
        status.className='lookup-status lookup-error';
        status.textContent='You selected a photo but have not cropped it. Click “Crop & Use Photo” before saving.';
        wrap.hidden=false;
        wrap.scrollIntoView({behavior:'smooth',block:'center'});
      }
    });
  }

  if(document.readyState==='loading'){
    document.addEventListener('DOMContentLoaded',init);
  }else{
    init();
  }
})();
