import requests, json, streamlit as st, os, time
import pandas as pd
from io import StringIO

# FastAPI endpoint
API_URL = os.environ.get("API_URL", "http://localhost:8000")

def auth_ui():
    if st.session_state.get("logged_in"):
        user = st.session_state.get("user", {})
        st.success(f"Logged in as {user.get('username', '')}")
        if st.button("Logout"):
            st.session_state.clear()
            st.rerun()
        return True

    mode = st.radio("Account", ["Login", "Create account"], horizontal=True)

    if mode == "Create account":
        with st.form("register_form"):
            st.markdown("#### Create account")
            new_username = st.text_input("Username", key="reg_user")
            new_email = st.text_input("Email (optional)", key="reg_email")
            new_password = st.text_input("Password", type="password", key="reg_pw")
            new_password2 = st.text_input("Confirm password", type="password", key="reg_pw2")
            register_btn = st.form_submit_button("Create account")

        if register_btn:
            if not new_username or not new_password:
                st.error("Username and password are required.")
            elif new_password != new_password2:
                st.error("Passwords do not match.")
            else:
                try:
                    r = requests.post(
                        f"{API_URL}/register",
                        json={
                            "username": new_username,
                            "email": (new_email.strip() or None),
                            "password": new_password,
                        },
                        timeout=10,
                    )
                    if r.status_code == 200:
                        st.success("Account created. Switch to Login.")
                    else:
                        st.error(r.json().get("detail", "Error creating account."))
                except requests.exceptions.RequestException:
                    st.error("Could not reach backend. Is FastAPI running?")
        return False

    # Login
    with st.form("login_form"):
        st.markdown("#### Login")
        username = st.text_input("Username", key="login_user")
        password = st.text_input("Password", type="password", key="login_pw")
        login_btn = st.form_submit_button("Login")

    if login_btn:
        try:
            r = requests.post(
                f"{API_URL}/login",
                json={"username": username, "password": password},
                timeout=10,
            )
            if r.status_code == 200:
                st.session_state["logged_in"] = True
                st.session_state["user"] = r.json().get("user", {})
                st.rerun()
            else:
                st.error("Invalid username or password.")
        except requests.exceptions.RequestException:
            st.error("Could not reach backend. Is FastAPI running?")

    return False


def main():
    st.title("BiLevel Optimization")
    
    if not auth_ui():
        st.stop()

    st.header("Overview")
    st.markdown(
        "Bilevel optimization, a class of hierarchical optimization problems, presents a significant research challenge due to its inherent NP-hard nature, especially in non-convex settings. In this work, we address the limitations of existing solvers. "
        + "Classical gradient-based methods are often inapplicable to the non-convex and non-differentiable landscapes common in practice, while derivative-free methods like nested evolutionary algorithms are rendered intractable by a prohibitively high query complexity. "
        + "\n\nTo this end, we propose a novel framework, the Surrogate-Assisted Co-evolutionary Evolutionary Strategy (SACE-ES), which synergizes the global search capabilities of evolutionary computation with the data-driven efficiency of surrogate modeling. "
        + "\n\nThe core innovation of our framework is a multi-surrogate, constraint-aware architecture that decouples the complex bilevel problem. We use separate Gaussian Process (GP) models to approximate the lower-level optimal solution vector and its corresponding constraint violations. "
        + "This allows our algorithm to make intelligent, cheap evaluations to guide the search, reserving expensive, true evaluations only for the most informative candidate solutions."
    )

    st.header("Authors")

    st.markdown(
        "_Sanup Araballi, Venkata Gandikota, Pranay Sharma, Prashant Khanduri, and Chilukuri K Mohan_"
    )

    st.write("[Github](https://github.com/sanuparaballi/SACEProject)")

    st.divider()

    with st.form("job_form"):
        email = st.text_input(
            "Email", key="signup_email", placeholder="you@example.com"
        )
        problem_file = st.file_uploader("Upload your problem file here", type=["json"])
        submitted_job = st.form_submit_button("Submit Job", use_container_width=True)

    if submitted_job:
        if problem_file and not problem_file.name.lower().endswith(".json"):
            st.error("Only .json files are allowed.")
        elif email and problem_file:
            try:
                # Read JSON file contents
                json_data = json.load(problem_file)
                json_data["email"] = email

                # Send POST request
                response = requests.post(
                    f"{API_URL}/submit_json", json={"data": json_data}
                )

                if response.status_code == 200:
                    result = response.json()
                    job_id = result['job_id']
                    st.success(f"Job {job_id} submitted successfully!")

                    # Display output area
                    st.subheader("Job Output:")
                    output_container = st.empty()
                    status_container = st.empty()
                    
                    # Poll for output
                    for _ in range(300):  # Poll for up to 10 minutes
                        time.sleep(2)  # Check every 2 seconds
                        
                        try:
                            output_response = requests.get(f"{API_URL}/job_output/{job_id}")
                            if output_response.status_code == 200:
                                data = output_response.json()
                                output_container.code(data['output'], language='text')
                                
                                if data['status'] == 'complete':
                                    status_container.success("Job Complete!")
                                    
                                    # Fetch results and save to session state instead of plotting immediately
                                    res = requests.get(f"{API_URL}/job_results/{job_id}")
                                    if res.status_code == 200:
                                        result_data = res.json().get("data", "")
                                        if result_data:
                                            # Save the raw CSV data into Streamlit's memory
                                            st.session_state["plot_data"] = result_data
                                        else:
                                            st.warning("Job completed, but no result data was returned.")
                                    break
                                elif data['status'] == 'failed':
                                    status_container.error("Job Failed")
                                    break
                                else:
                                    status_container.info(f"Status: {data['status']}")
                        except Exception as e:
                            status_container.error(f"Error: {str(e)}")
                            break

                else:
                    st.error("Failed to submit job to backend.")
            except json.JSONDecodeError:
                st.error("Invalid JSON file.")
            except Exception as e:
                st.error(f"Error: {str(e)}")
        else:
            st.warning("Please enter an email and upload a file.")
            
    if "plot_data" in st.session_state:
        st.divider()
        st.subheader("📊 Optimization Results & Analysis")
        try:
            # Parse CSV data
            df = pd.read_csv(StringIO(st.session_state["plot_data"]))
            
            # 1. Data Preview
            with st.expander("View Raw Data Table"):
                st.dataframe(df, use_container_width=True) 
            
            # 2. Advanced Graphing Options (Requirement TM11-43)
            st.write("### Performance Visualization")
            numeric_cols = df.select_dtypes(include=['float64', 'int64']).columns.tolist()
            
            if len(numeric_cols) >= 1:
                col1, col2, col3 = st.columns([1, 1, 1])
                
                with col1:
                    chart_type = st.selectbox(
                        "Chart Type", 
                        ["Line", "Bar", "Area", "Scatter"],
                        help="Choose the visualization style for your problem type."
                    )
                
                with col2:
                    # Allow user to pick X-axis (e.g., 'iteration', 'time', or 'parameter')
                    x_axis = st.selectbox("X-Axis (Independent Variable)", numeric_cols, index=0)
                
                with col3:
                    # Multi-select for Y-axes
                    y_axes = st.multiselect(
                        "Y-Axes (Metrics)", 
                        numeric_cols, 
                        default=[numeric_cols[-1]] if len(numeric_cols) > 1 else [numeric_cols[0]]
                    )

                if y_axes:
                    # Create the selected chart type
                    plot_df = df.set_index(x_axis)[y_axes]
                    
                    if chart_type == "Line":
                        st.line_chart(plot_df)
                    elif chart_type == "Bar":
                        st.bar_chart(plot_df)
                    elif chart_type == "Area":
                        st.area_chart(plot_df)
                    elif chart_type == "Scatter":
                        # For scatter, we use st.scatter_chart (Streamlit 1.25+)
                        st.scatter_chart(df, x=x_axis, y=y_axes)
                else:
                    st.info("Select at least one metric to visualize results.")
            else:
                st.warning("The output data contains no numeric values for graphing.")

        except Exception as e:
            st.error(f"Error parsing or plotting data: {e}")

        except Exception as e:
            st.error(f"Error parsing or plotting data: {e}")

    st.divider()
    st.subheader("Submitted Jobs")

    # Fetch jobs from the database (persists across refreshes)
    try:
        response = requests.get(f"{API_URL}/get_submissions")
        if response.status_code == 200:
            all_submissions = response.json()["submissions"]
            # Filter to only show JSON submissions (actual jobs)
            json_jobs = [sub for sub in all_submissions if sub["type"] == "json"]
            
            if json_jobs:
                for i, job in enumerate(json_jobs, 1):
                    job_data = job["data"].get("data", {})
                    job_email = job_data.get("email", "Unknown")
                    job_status = job.get("status", "unknown")
                    st.write(f"Job {job['id']} — {job_email} — Status: {job_status}")
            else:
                st.info("No jobs submitted yet.")
        else:
            st.error("Failed to fetch jobs from database.")
    except requests.exceptions.RequestException:
        st.error("Could not connect to backend. Make sure the server is running.")

main()
