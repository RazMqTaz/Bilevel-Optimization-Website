import requests, json, streamlit as st, os, time
import pandas as pd
from io import StringIO

# FastAPI endpoint
API_URL = os.environ.get("API_URL", "http://localhost:8000")


def auth_headers() -> dict:
    """Return Authorization header using the stored session token."""
    token = st.session_state.get("token")
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}


def auth_ui():
    if st.session_state.get("logged_in"):
        user = st.session_state.get("user", {})
        st.success(f"Logged in as {user.get('username', '')}")
        if st.button("Logout"):
            # Invalidate session on the backend
            try:
                requests.post(
                    f"{API_URL}/logout",
                    headers=auth_headers(),
                    timeout=10,
                )
            except requests.exceptions.RequestException:
                pass
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
            new_password2 = st.text_input(
                "Confirm password", type="password", key="reg_pw2"
            )
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
                data = r.json()
                st.session_state["logged_in"] = True
                st.session_state["user"] = data.get("user", {})
                st.session_state["token"] = data.get("token", "")
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

    # ── Job Submission ────────────────────────────────────────────────────────

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
                json_data = json.load(problem_file)
                json_data["email"] = email

                response = requests.post(
                    f"{API_URL}/submit_json",
                    json={"data": json_data},
                    headers=auth_headers(),
                )

                if response.status_code == 200:
                    result = response.json()
                    job_id = result["job_id"]
                    st.success(f"Job {job_id} submitted successfully!")

                    st.subheader("Job Output:")
                    output_container = st.empty()
                    status_container = st.empty()

                    # Poll for output
                    for _ in range(300):  # Up to ~10 minutes
                        time.sleep(2)

                        try:
                            output_response = requests.get(
                                f"{API_URL}/job_output/{job_id}",
                                headers=auth_headers(),
                            )
                            if output_response.status_code == 200:
                                data = output_response.json()
                                output_container.code(data["output"], language="text")

                                if data["status"] == "complete":
                                    status_container.success("Job Complete!")
                                    # Fetch result CSV and save for plotting
                                    res = requests.get(
                                        f"{API_URL}/job_results/{job_id}",
                                        headers=auth_headers(),
                                    )
                                    if res.status_code == 200:
                                        result_csv = res.json().get("data", "")
                                        if result_csv:
                                            st.session_state["plot_data"] = result_csv
                                        else:
                                            st.warning("Job completed, but no result data was returned.")
                                    break
                                elif data["status"] == "failed":
                                    status_container.error("Job Failed")
                                    break
                                else:
                                    status_container.info(f"Status: {data['status']}")
                            elif output_response.status_code == 401:
                                status_container.error("Session expired. Please log in again.")
                                st.session_state.clear()
                                break
                        except Exception as e:
                            status_container.error(f"Error: {str(e)}")
                            break

                elif response.status_code == 401:
                    st.error("Session expired. Please log in again.")
                    st.session_state.clear()
                    st.rerun()
                else:
                    st.error("Failed to submit job to backend.")
            except json.JSONDecodeError:
                st.error("Invalid JSON file.")
            except Exception as e:
                st.error(f"Error: {str(e)}")
        else:
            st.warning("Please enter an email and upload a file.")

    # ── Results Graph ─────────────────────────────────────────────────────────

    if "plot_data" in st.session_state:
        st.divider()
        st.subheader("Optimization Results")
        try:
            df = pd.read_csv(StringIO(st.session_state["plot_data"]))
            st.dataframe(df)

            st.write("### Performance Graph")
            numeric_cols = df.select_dtypes(include=["float64", "int64"]).columns.tolist()

            if numeric_cols:
                y_axes = st.multiselect(
                    "Select metrics to plot:",
                    numeric_cols,
                    default=[numeric_cols[0]],
                    key="metric_selector",
                )
                if y_axes:
                    st.line_chart(df[y_axes])
            else:
                st.info("No numeric data found to plot.")
        except Exception as e:
            st.error(f"Error parsing or plotting data: {e}")

    st.divider()

    # ── User's Jobs ───────────────────────────────────────────────────────────

    st.subheader("My Jobs")

    try:
        response = requests.get(
            f"{API_URL}/my_jobs",
            headers=auth_headers(),
        )
        if response.status_code == 200:
            jobs = response.json()["jobs"]

            if jobs:
                # Results table + CSV download
                table_rows = []
                for job in jobs:
                    job_data = job.get("data", {}).get("data", {})
                    table_rows.append(
                        {
                            "id": job.get("id"),
                            "email": job_data.get("email", ""),
                            "type": job.get("type", ""),
                            "status": job.get("status", ""),
                            "created_at": job.get("created_at", ""),
                        }
                    )

                jobs_df = pd.DataFrame(table_rows)
                csv_bytes = jobs_df.to_csv(index=False).encode("utf-8")
                st.download_button(
                    label="Download DB results (CSV)",
                    data=csv_bytes,
                    file_name="my_jobs.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
                st.dataframe(jobs_df, use_container_width=True, hide_index=True)

                for job in jobs:
                    job_data = job["data"].get("data", {})
                    job_email = job_data.get("email", "Unknown")
                    job_status = job.get("status", "unknown")

                    status_icon = {
                        "complete": "✅",
                        "failed": "❌",
                        "running": "🔄",
                        "pending": "⏳",
                    }.get(job_status, "❓")

                    with st.expander(
                        f"{status_icon} Job {job['id']} — {job_email} — {job_status}"
                    ):
                        # Show output if job has run
                        try:
                            out_resp = requests.get(
                                f"{API_URL}/job_output/{job['id']}",
                                headers=auth_headers(),
                            )
                            if out_resp.status_code == 200:
                                out_data = out_resp.json()
                                if out_data["output"]:
                                    st.code(out_data["output"], language="text")
                                else:
                                    st.info("No output yet.")
                        except requests.exceptions.RequestException:
                            st.warning("Could not fetch job output.")
            else:
                st.info("No jobs submitted yet.")
        elif response.status_code == 401:
            st.error("Session expired. Please log in again.")
            st.session_state.clear()
            st.rerun()
        else:
            st.error("Failed to fetch jobs.")
    except requests.exceptions.RequestException:
        st.error("Could not connect to backend. Make sure the server is running.")


main()