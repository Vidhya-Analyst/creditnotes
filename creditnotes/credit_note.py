import pandas as pd
from connector.db_connector import get_db_conn
from datetime import datetime, timedelta
import frappe
import json
import os
import pypdf
import io as IO

def get_fac_trans_df(conn, start_date, end_date):
    sql = "EXEC zpu_List_Fac_Transactions ?,?"
    values = (start_date, end_date)
    df = pd.read_sql(sql, con=conn, params=values)
    df.columns = map(str.lower, df.columns)
    return df

def extract_fac_transactions(doc):
    if isinstance(doc.month, str):
        doc.month = datetime.strptime(doc.month, "%Y-%m-%d").date()
    if doc.month.month == 12:
        next_month = doc.month.replace(year=doc.month.year + 1, month=1, day=1)
    else:
        next_month = doc.month.replace(month=doc.month.month + 1, day=1)

    start_date = doc.month.replace(day=1)
    end_date = next_month - timedelta(days=1)

    frappe.msgprint(f"Extracting FacTransactions from {start_date} to {end_date}")

    force_refresh = doc.force_refresh
    conn = get_db_conn(live=True)
    df = get_fac_trans_df(conn, start_date, end_date)

    if force_refresh:
        #Delete all FacTransaction records within the date range
        existing_docs = frappe.get_all("FacTransaction", filters = [['document_date', '>=', start_date],
                                                    ['document_date', '<=', end_date]])
        for doc in existing_docs:
            frappe.delete_doc("FacTransaction", doc.name, force=True)

    #Insert FacTransaction records
    for row in df.to_dict('records'):
        doc_ref_code = row['document_ref'][:3]
        #Check if the policy is for New Business or Renewal
        if (doc_ref_code == 'SND') or (doc_ref_code == 'SRD'):
            row['doctype'] = "FacTransaction"
            row['status'] = 'Saved'
            row['parent_dates'] = doc.name
            fac_notice = frappe.get_doc(row)
            fac_notice.insert(ignore_if_duplicate=(not force_refresh))
    return

def get_reins_df(conn, docref):
    sql = "exec zpu_Get_Fac_transactions ?"
    values = (docref)
    df = pd.read_sql(sql, con=conn, params=values)
    df.columns = map(str.lower, df.columns)
    df = df[['shortname', 'ri_arrangement_line_id', 'riskdescription', 'vatrate', 'party_cnt', 
             'this_share_percent', 'premium_percent', 'commission_percent', 'sum_insured', 'premium_value', 
             'commission_value', 'premium_tax', 'commission_tax', 'is_commission_modified']]
    return df

def get_reins_address(conn, row):
    sql = "exec ZPU_GET_CORRESPOND_ADD ?"
    values = (row['party_cnt'])
    df = pd.read_sql(sql, con=conn, params=values)
    address = f"{str(df['address1'].iloc[0])}\n{str(df['address2'].iloc[0])}\n{str(df['address3'].iloc[0])}\n{str(df['Postal_code'].iloc[0])}\n{str(df['Country'].iloc[0])}"
    address = os.linesep.join([s for s in address.splitlines() if s.strip()])
    return address

def get_reins_email(conn, row):
    sql = "select * from QRYEmail_Addresses where party_cnt = ?"
    values = (row['party_cnt'])
    df = pd.read_sql(sql, con=conn, params=values)
    emails = '|'.join(df['Email'])
    return emails

def get_reins_name(conn, row):
    sql = "select TOP 1 resolved_name from Party where party_cnt = ?"
    values = (row['party_cnt'])
    df = pd.read_sql(sql, con=conn, params=values)
    return df['resolved_name'].iloc[0]

def extract_reins_details(doc):
    doc = json.loads(doc)

    conn = get_db_conn(live=True)
    df = get_reins_df(conn, doc['document_ref'])

    #Delete all Reinsurer records for the FacTransaction
    frappe_doc = frappe.get_doc('FacTransaction', doc['name'])
    frappe_doc.reinsurers = []

    #Insert Reinsurer records
    for row in df.to_dict('records'):
        row['address'] = get_reins_address(conn, row)
        row['emails'] = get_reins_email(conn, row)
        row['resolved_name'] = get_reins_name(conn, row)
        frappe_doc.append('reinsurers', row)

    frappe_doc.save()
    frappe.msgprint(f"Extracted {len(df)} Reinsurers.")
    return frappe_doc.as_json()

@frappe.whitelist()
def print_credit_notes(doc):
    doc = json.loads(extract_reins_details(doc))

    #Check if Reinsurers are present
    if not doc['reinsurers']:
        frappe.throw("No Reinsurers found for this FacTransaction, therefore cannot print any Credit Notes.")
        return

    #Check if the FacTransaction is already printed and delete the existing files
    if doc['status'] == 'Printed':
        #Delete all files attached to the FacTransaction
        existing_files = frappe.get_all("File",
                filters={
                    "attached_to_doctype": doc['doctype'],
                    "attached_to_name": doc['name'],
                },fields=["name"])
        for file_doc in existing_files:
            frappe.delete_doc("File", file_doc.name, force=True)

    pdf_content = frappe.get_print(doc['doctype'], doc['name'], 'Credit Note', as_pdf=True)
    pdf_file = pypdf.PdfReader(stream = IO.BytesIO(pdf_content))

    #Verify that the number of reinsurers matches the number of pages in the PDF 
    if len(doc['reinsurers']) != len(pdf_file.pages):
        file_doc = frappe.get_doc({
                "doctype": "File",
                "file_name": f"ALL-{doc['name']}.pdf",
                "attached_to_doctype": doc['doctype'],
                "attached_to_name": doc['name'],
                "content": pdf_content,
                "is_private": 0
            })
        file_doc.save(ignore_permissions=True)
        frappe.msgprint(f"Number of reinsurers does not match number of pages in the PDF. {len(doc['reinsurers'])} reinsurers and {len(pdf_file.pages)} pages.")
        return

    for i in range(len(pdf_file.pages)):
        pdf_writer = pypdf.PdfWriter()
        pdf_writer.add_page(pdf_file.pages[i])
        pdf_page_stream = IO.BytesIO()
        pdf_writer.write(pdf_page_stream)

        short_name = doc['reinsurers'][i]['shortname'].strip()
        file_name = f"{short_name}-{i}-{doc['name']}-CN.pdf"

        file_doc = frappe.get_doc({
                "doctype": "File",
                "file_name": file_name,
                "attached_to_doctype": doc['doctype'],
                "attached_to_name": doc['name'],
                "content": pdf_page_stream.getvalue(),
                "is_private": 0
            })
        file_doc.save(ignore_permissions=True)

    frappe.msgprint(f"Credit Note PDF generated and attached.")
    frappe.db.set_value('FacTransaction', doc['name'], 'status', 'Printed')
    
@frappe.whitelist()
def print_credit_notes_fc(doc):
    # frappe.msgprint("This function is deprecated. Please use the new 'print_credit_notes_fc' function instead.")
    doc = json.loads(extract_reins_details(doc))

    #Check if Reinsurers are present
    if not doc['reinsurers']:
        frappe.throw("No Reinsurers found for this FacTransaction, therefore cannot print any Credit Notes.")
        return

    #Check if the FacTransaction is already printed and delete the existing files
    if doc['status'] == 'Printed':
        #Delete all files attached to the FacTransaction
        existing_files = frappe.get_all("File",
                filters={
                    "attached_to_doctype": doc['doctype'],
                    "attached_to_name": doc['name'],
                },fields=["name"])
        for file_doc in existing_files:
            frappe.delete_doc("File", file_doc.name, force=True)

    pdf_content = frappe.get_print(doc['doctype'], doc['name'], 'Credit Note FC', as_pdf=True)
    pdf_file = pypdf.PdfReader(stream = IO.BytesIO(pdf_content))

    #Verify that the number of reinsurers matches the number of pages in the PDF 
    if len(doc['reinsurers']) != len(pdf_file.pages):
        file_doc = frappe.get_doc({
                "doctype": "File",
                "file_name": f"ALL-{doc['name']}.pdf",
                "attached_to_doctype": doc['doctype'],
                "attached_to_name": doc['name'],
                "content": pdf_content,
                "is_private": 0
            })
        file_doc.save(ignore_permissions=True)
        frappe.msgprint(f"Number of reinsurers does not match number of pages in the PDF. {len(doc['reinsurers'])} reinsurers and {len(pdf_file.pages)} pages.")
        return

    for i in range(len(pdf_file.pages)):
        pdf_writer = pypdf.PdfWriter()
        pdf_writer.add_page(pdf_file.pages[i])
        pdf_page_stream = IO.BytesIO()
        pdf_writer.write(pdf_page_stream)

        short_name = doc['reinsurers'][i]['shortname'].strip()
        file_name = f"{short_name}-{i}-{doc['name']}-CN.pdf"

        file_doc = frappe.get_doc({
                "doctype": "File",
                "file_name": file_name,
                "attached_to_doctype": doc['doctype'],
                "attached_to_name": doc['name'],
                "content": pdf_page_stream.getvalue(),
                "is_private": 0
            })
        file_doc.save(ignore_permissions=True)

    frappe.msgprint(f"Credit Note PDF generated and attached.")
    frappe.db.set_value('FacTransaction', doc['name'], 'status', 'Printed')