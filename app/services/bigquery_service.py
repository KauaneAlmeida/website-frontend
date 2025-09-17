"""
BigQuery Service

This module provides integration with Google BigQuery for data warehouse operations.
Uses batch loading (load_table_from_json) which is compatible with BigQuery Sandbox (free tier).
"""

import os
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from google.cloud import bigquery
from google.cloud.exceptions import GoogleCloudError

# Configure logging
logger = logging.getLogger(__name__)

class BigQueryService:
    """Service for BigQuery data warehouse operations."""
    
    def __init__(self, project_id: str = "js-quiz-fiap-b1e86", credentials_path: str = "service-account.json"):
        """
        Initialize BigQuery service.
        
        Args:
            project_id (str): Google Cloud project ID
            credentials_path (str): Path to service account JSON file
        """
        self.project_id = project_id
        self.credentials_path = credentials_path
        self.client = None
        self.dataset_id = "leads_dataset"
        self.table_id = "leads"
        self.full_table_id = f"{project_id}.{self.dataset_id}.{self.table_id}"
        
        self._initialize_client()
    
    def _initialize_client(self):
        """Initialize BigQuery client with service account credentials."""
        try:
            # Check if credentials file exists
            if not os.path.exists(self.credentials_path):
                raise FileNotFoundError(f"Service account file not found: {self.credentials_path}")
            
            # Set environment variable for authentication
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = self.credentials_path
            
            # Initialize BigQuery client
            self.client = bigquery.Client(project=self.project_id)
            
            logger.info(f"✅ BigQuery client initialized successfully for project: {self.project_id}")
            
        except Exception as e:
            logger.error(f"❌ Error initializing BigQuery client: {str(e)}")
            raise
    
    def inserir_evento_lead(
        self, 
        lead_id: str, 
        advogado_id: str, 
        foi_notificado: bool, 
        respondeu: bool
    ) -> bool:
        """
        Insert a lead event into BigQuery using batch loading.
        
        Args:
            lead_id (str): Unique identifier for the lead
            advogado_id (str): Unique identifier for the lawyer
            foi_notificado (bool): Whether the lawyer was notified
            respondeu (bool): Whether the lawyer responded
            
        Returns:
            bool: True if insertion was successful, False otherwise
        """
        try:
            if not self.client:
                raise Exception("BigQuery client not initialized")
            
            # Get current UTC timestamp
            current_time = datetime.now(timezone.utc)
            
            # Prepare data for insertion
            row_data = {
                "lead_id": lead_id,
                "advogado_id": advogado_id,
                "foi_notificado": foi_notificado,
                "respondeu": respondeu,
                "data_evento": current_time.isoformat()
            }
            
            logger.info(f"📊 Inserting lead event: {lead_id} -> {advogado_id}")
            logger.debug(f"Row data: {row_data}")
            
            # Get table reference
            table_ref = self.client.get_table(self.full_table_id)
            
            # Configure load job
            job_config = bigquery.LoadJobConfig(
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                autodetect=False  # Use existing table schema
            )
            
            # Load data using batch loading (compatible with free tier)
            load_job = self.client.load_table_from_json(
                [row_data], 
                table_ref, 
                job_config=job_config
            )
            
            # Wait for job completion
            load_job.result()  # Waits for the job to complete
            
            if load_job.errors:
                logger.error(f"❌ BigQuery load job errors: {load_job.errors}")
                return False
            
            logger.info(f"✅ Lead event inserted successfully: {lead_id}")
            print(f"✅ SUCCESS: Lead event inserted into BigQuery")
            print(f"   Lead ID: {lead_id}")
            print(f"   Advogado ID: {advogado_id}")
            print(f"   Foi Notificado: {foi_notificado}")
            print(f"   Respondeu: {respondeu}")
            print(f"   Data Evento: {current_time.isoformat()}")
            
            return True
            
        except GoogleCloudError as gcp_error:
            error_msg = f"Google Cloud error inserting lead event: {str(gcp_error)}"
            logger.error(f"❌ {error_msg}")
            print(f"❌ ERROR: {error_msg}")
            return False
            
        except Exception as e:
            error_msg = f"Unexpected error inserting lead event: {str(e)}"
            logger.error(f"❌ {error_msg}")
            print(f"❌ ERROR: {error_msg}")
            return False
    
    def inserir_multiplos_eventos(self, eventos: List[Dict[str, Any]]) -> bool:
        """
        Insert multiple lead events in a single batch operation.
        
        Args:
            eventos (list): List of event dictionaries with keys:
                          lead_id, advogado_id, foi_notificado, respondeu
                          
        Returns:
            bool: True if all insertions were successful, False otherwise
        """
        try:
            if not self.client:
                raise Exception("BigQuery client not initialized")
            
            if not eventos:
                logger.warning("⚠️ No events provided for batch insertion")
                return True
            
            # Get current UTC timestamp
            current_time = datetime.now(timezone.utc)
            
            # Prepare batch data
            batch_data = []
            for evento in eventos:
                row_data = {
                    "lead_id": evento["lead_id"],
                    "advogado_id": evento["advogado_id"],
                    "foi_notificado": evento["foi_notificado"],
                    "respondeu": evento["respondeu"],
                    "data_evento": current_time.isoformat()
                }
                batch_data.append(row_data)
            
            logger.info(f"📊 Inserting {len(batch_data)} lead events in batch")
            
            # Get table reference
            table_ref = self.client.get_table(self.full_table_id)
            
            # Configure load job
            job_config = bigquery.LoadJobConfig(
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                autodetect=False
            )
            
            # Load data using batch loading
            load_job = self.client.load_table_from_json(
                batch_data, 
                table_ref, 
                job_config=job_config
            )
            
            # Wait for job completion
            load_job.result()
            
            if load_job.errors:
                logger.error(f"❌ BigQuery batch load job errors: {load_job.errors}")
                return False
            
            logger.info(f"✅ {len(batch_data)} lead events inserted successfully")
            print(f"✅ SUCCESS: {len(batch_data)} lead events inserted into BigQuery")
            
            return True
            
        except Exception as e:
            error_msg = f"Error inserting batch lead events: {str(e)}"
            logger.error(f"❌ {error_msg}")
            print(f"❌ ERROR: {error_msg}")
            return False
    
    def verificar_conexao(self) -> bool:
        """
        Verify BigQuery connection and table access.
        
        Returns:
            bool: True if connection is successful, False otherwise
        """
        try:
            if not self.client:
                raise Exception("BigQuery client not initialized")
            
            # Try to get table information
            table = self.client.get_table(self.full_table_id)
            
            logger.info(f"✅ BigQuery connection verified")
            logger.info(f"   Table: {table.full_table_id}")
            logger.info(f"   Rows: {table.num_rows}")
            logger.info(f"   Schema fields: {len(table.schema)}")
            
            print(f"✅ BigQuery connection successful!")
            print(f"   Project: {self.project_id}")
            print(f"   Dataset: {self.dataset_id}")
            print(f"   Table: {self.table_id}")
            print(f"   Total rows: {table.num_rows}")
            
            return True
            
        except Exception as e:
            error_msg = f"BigQuery connection verification failed: {str(e)}"
            logger.error(f"❌ {error_msg}")
            print(f"❌ ERROR: {error_msg}")
            return False
    
    def obter_estatisticas_tabela(self) -> Optional[Dict[str, Any]]:
        """
        Get table statistics and information.
        
        Returns:
            Dict with table statistics or None if error
        """
        try:
            if not self.client:
                raise Exception("BigQuery client not initialized")
            
            table = self.client.get_table(self.full_table_id)
            
            stats = {
                "project_id": table.project,
                "dataset_id": table.dataset_id,
                "table_id": table.table_id,
                "full_table_id": table.full_table_id,
                "num_rows": table.num_rows,
                "num_bytes": table.num_bytes,
                "created": table.created.isoformat() if table.created else None,
                "modified": table.modified.isoformat() if table.modified else None,
                "schema_fields": [
                    {
                        "name": field.name,
                        "field_type": field.field_type,
                        "mode": field.mode
                    }
                    for field in table.schema
                ]
            }
            
            logger.info(f"📊 Table statistics retrieved for {self.full_table_id}")
            return stats
            
        except Exception as e:
            logger.error(f"❌ Error getting table statistics: {str(e)}")
            return None


# Global service instance
bigquery_service = BigQueryService()

# Convenience function for direct import
def inserir_evento_lead(lead_id: str, advogado_id: str, foi_notificado: bool, respondeu: bool) -> bool:
    """
    Convenience function to insert a lead event.
    
    Args:
        lead_id (str): Unique identifier for the lead
        advogado_id (str): Unique identifier for the lawyer
        foi_notificado (bool): Whether the lawyer was notified
        respondeu (bool): Whether the lawyer responded
        
    Returns:
        bool: True if insertion was successful, False otherwise
    """
    return bigquery_service.inserir_evento_lead(lead_id, advogado_id, foi_notificado, respondeu)