import os
from pathlib import Path
import streamlit as st



def main():
    st.title("BiLevel Optimization")
    
    st.header("Overview")
    st.markdown("Bilevel optimization, a class of hierarchical optimization problems, presents a significant research challenge due to its inherent NP-hard nature, especially in non-convex settings. In this work, we address the limitations of existing solvers. "
                +"Classical gradient-based methods are often inapplicable to the non-convex and non-differentiable landscapes common in practice, while derivative-free methods like nested evolutionary algorithms are rendered intractable by a prohibitively high query complexity. "
                +"\n\nTo this end, we propose a novel framework, the Surrogate-Assisted Co-evolutionary Evolutionary Strategy (SACE-ES), which synergizes the global search capabilities of evolutionary computation with the data-driven efficiency of surrogate modeling. "
                +"\n\nThe core innovation of our framework is a multi-surrogate, constraint-aware architecture that decouples the complex bilevel problem. We use separate Gaussian Process (GP) models to approximate the lower-level optimal solution vector and its corresponding constraint violations. "
                +"This allows our algorithm to make intelligent, cheap evaluations to guide the search, reserving expensive, true evaluations only for the most informative candidate solutions.")

    st.header("Authors")

    st.markdown("_Sanup Araballi, Venkata Gandikota, Pranay Sharma, Prashant Khanduri, and Chilukuri K Mohan_")
    
    st.write("[Github](https://github.com/sanuparaballi/SACEProject)")


    st.divider()
    
    st.session_state.jobs = []
    
    with st.form("job_form", enter_to_submit=True):
        email = st.text_input("Email", key="signup_email", placeholder="you@example.com")
        problem_file = st.file_uploader("Upload your problem file here")
        submitted_job = st.form_submit_button("Submit Job", use_container_width=True)
        
    if submitted_job:
        if email and problem_file:
            # Save the file locally
            save_dir = Path("uploads")
            save_dir.mkdir(exist_ok=True)
            file_path = save_dir / problem_file.name
            with open(file_path, "wb") as f:
                f.write(problem_file.getbuffer())

            # Add job info to the jobs list
            st.session_state.jobs.append({
                "email": email,
                "filename": problem_file.name,
                "path": str(file_path)
            })

            st.success(f"Job submitted successfully for {email}")
        else:
            st.warning("Please enter an email and upload a file.")
        
    
    st.divider()
    st.subheader("Submitted Jobs")
    
    # Show all jobs for now
    if st.session_state.jobs:
        for i, job in enumerate(st.session_state.jobs, 1):
            st.write(f"Job {i} — {job['email']} | File: `{job['filename']}`")
    
main()