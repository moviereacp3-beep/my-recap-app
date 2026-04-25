import streamlit as st

st.set_page_config(page_title="Movie Recap AI", layout="centered")

st.title("🎬 Movie Recap AI Tool")
st.write("---")

# Sidebar မှာ API Key ထည့်ခိုင်းမယ်
api_key = st.sidebar.text_input("Groq API Key ကို ဒီမှာထည့်ပါ", type="password")

if api_key:
    st.success("✅ API Key အဆင်ပြေပါတယ်။")
    
    # ဖိုင်တင်တဲ့နေရာ
    uploaded_file = st.file_uploader("ဇာတ်လမ်းအကျဉ်းဖိုင် သို့မဟုတ် ဗီဒီယို တင်ပါ", type=['txt', 'mp4'])
    
    if uploaded_file:
        st.info("AI က ဇာတ်ကြောင်းကို စတင်ဖန်တီးနေပါပြီ...")
        # ဒီနေရာမှာ recap လုပ်မယ့် ကုဒ်တွေ ဆက်ရေးလို့ရပါတယ်
else:
    st.warning("⚠️ ရှေ့ဆက်ဖို့အတွက် ဘေးက Sidebar မှာ API Key အရင်ထည့်ပေးပါ။")

