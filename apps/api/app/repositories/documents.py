"""Document metadata, extraction history, and worker jobs."""
import json

class DocumentRepository:
    def __init__(self,db): self.db=db
    def list_active(self,rid): return self.db.execute('SELECT * FROM project_documents WHERE request_id=? AND removed_at IS NULL ORDER BY created_at,document_id',(rid,)).fetchall()
    def get(self,rid,did): return self.db.execute('SELECT * FROM project_documents WHERE request_id=? AND document_id=?',(rid,did)).fetchone()
    def get_any(self,did): return self.db.execute('SELECT * FROM project_documents WHERE document_id=?',(did,)).fetchone()
    def extraction(self,did,revision): return self.db.execute('SELECT * FROM document_extractions WHERE document_id=? AND extraction_revision=?',(did,revision)).fetchone()
    def count_active(self,rid):
        row = self.db.execute('SELECT count(*) AS n FROM project_documents WHERE request_id=? AND removed_at IS NULL',(rid,)).fetchone()
        return row['n']
    def create(self,key,rid,filename,mime,size,at):
        self.db.execute("INSERT INTO project_documents(document_id,request_id,original_filename,mime_type,file_size_bytes,storage_key,extraction_status,extraction_revision,created_at) VALUES(?,?,?,?,?,?,'pending',1,?)",(key,rid,filename,mime,size,key,at))
        self.create_extraction(key,1,at)
    def create_extraction(self,did,revision,at): self.db.execute("INSERT INTO document_extractions(document_id,extraction_revision,extraction_status,created_at) VALUES(?,?,'pending',?)",(did,revision,at))
    def bump_input(self,rid,at): self.db.execute('UPDATE roadmap_inputs SET input_revision=input_revision+1,updated_at=? WHERE request_id=?',(at,rid))
    def remove(self,did,at): self.db.execute("UPDATE project_documents SET removed_at=?,cleanup_status='queued',extraction_lease_token=NULL,extraction_lease_until=NULL WHERE document_id=?",(at,did))
    def retry(self,did,revision,at):
        self.db.execute("UPDATE project_documents SET extraction_status='pending',extraction_revision=?,partial_confirmed_at=NULL,extraction_error_code=NULL,extraction_lease_token=NULL,extraction_lease_until=NULL WHERE document_id=?",(revision,did)); self.create_extraction(did,revision,at)
    def confirm(self,did,at): self.db.execute('UPDATE project_documents SET partial_confirmed_at=? WHERE document_id=?',(at,did))
    def next_job(self,at):
        sql = """SELECT * FROM project_documents WHERE (removed_at IS NULL AND extraction_status='pending' AND (extraction_lease_until IS NULL OR extraction_lease_until<?)) OR (removed_at IS NOT NULL AND cleanup_status IN ('queued','failed','running') AND (cleanup_lease_until IS NULL OR cleanup_lease_until<?)) ORDER BY created_at LIMIT 1"""
        if getattr(self.db, 'backend', 'sqlite') == 'postgres':
            sql += ' FOR UPDATE SKIP LOCKED'
        return self.db.execute(sql,(at,at)).fetchone()
    def lease(self,did,token,until,cleanup):
        if cleanup: self.db.execute("UPDATE project_documents SET cleanup_status='running',cleanup_lease_token=?,cleanup_lease_until=?,cleanup_attempts=cleanup_attempts+1 WHERE document_id=?",(token,until,did))
        else: self.db.execute('UPDATE project_documents SET extraction_lease_token=?,extraction_lease_until=?,extraction_attempts=extraction_attempts+1 WHERE document_id=?',(token,until,did))
    def finish_cleanup(self,did,token):
        if getattr(self.db, 'backend', 'sqlite') == 'postgres':
            self.db.execute('SELECT document_id FROM project_documents WHERE document_id=? FOR UPDATE',(did,)).fetchone()
        row=self.get_any(did)
        if row and row['cleanup_lease_token']==token:
            self.db.execute('DELETE FROM document_extractions WHERE document_id=?',(did,))
            self.db.execute("UPDATE project_documents SET cleanup_status='succeeded',cleanup_lease_token=NULL,cleanup_lease_until=NULL,cleanup_error_code=NULL WHERE document_id=?",(did,))
    def fail_cleanup(self,did,token,retry_at):
        self.db.execute("UPDATE project_documents SET cleanup_status='failed',cleanup_error_code='storage_cleanup_failed',cleanup_lease_token=NULL,cleanup_lease_until=? WHERE document_id=? AND cleanup_lease_token=?",(retry_at,did,token))
    def finish_extraction(self,row,token,result,at):
        if getattr(self.db, 'backend', 'sqlite') == 'postgres':
            # Match the API's lock order: plan first, document second.
            self.db.execute('SELECT request_id FROM roadmap_inputs WHERE request_id=? FOR UPDATE',(row['request_id'],)).fetchone()
            self.db.execute('SELECT document_id FROM project_documents WHERE document_id=? FOR UPDATE',(row['document_id'],)).fetchone()
        did=row['document_id']; current=self.get_any(did)
        if current and current['removed_at'] is None and current['extraction_status']=='pending' and current['extraction_revision']==row['extraction_revision'] and current['extraction_lease_token']==token:
            if getattr(self.db, 'backend', 'sqlite') == 'postgres':
                from psycopg.types.json import Jsonb
                segments, limitations = Jsonb(result['segments']), Jsonb(result['limitations'])
            else:
                segments, limitations = json.dumps(result['segments'],ensure_ascii=False), json.dumps(result['limitations'],ensure_ascii=False)
            self.db.execute('''UPDATE document_extractions SET extracted_text=?,segments=?,limitations=?,extraction_status=?,error_code=?,finished_at=? WHERE document_id=? AND extraction_revision=? AND extraction_status='pending' ''',(result['text'],segments,limitations,result['status'],result['error_code'],at,did,row['extraction_revision']))
            self.db.execute('UPDATE project_documents SET extraction_status=?,extraction_error_code=?,extraction_lease_until=NULL,extraction_lease_token=NULL WHERE document_id=?',(result['status'],result['error_code'],did))
            self.bump_input(row['request_id'],at)
    def has_storage_key(self,key): return bool(self.db.execute('SELECT 1 FROM project_documents WHERE storage_key=?',(key,)).fetchone())
