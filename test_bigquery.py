"""
BigQuery Service Test

Test file to validate BigQuery integration functionality.
Tests the inserir_evento_lead function with dummy data.
"""

import sys
import os
import logging
from datetime import datetime

# Add the app directory to Python path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

# Import the function to test
from services.bigquery_service import inserir_evento_lead, bigquery_service

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_single_lead_insertion():
    """Test inserting a single lead event."""
    print("\n" + "="*60)
    print("🧪 TESTING: Single Lead Event Insertion")
    print("="*60)
    
    try:
        # Test data
        lead_id = "lead_001"
        advogado_id = "advogado_123"
        foi_notificado = True
        respondeu = False
        
        print(f"📝 Test Data:")
        print(f"   Lead ID: {lead_id}")
        print(f"   Advogado ID: {advogado_id}")
        print(f"   Foi Notificado: {foi_notificado}")
        print(f"   Respondeu: {respondeu}")
        print(f"   Timestamp: {datetime.now()}")
        
        # Call the function
        result = inserir_evento_lead(lead_id, advogado_id, foi_notificado, respondeu)
        
        if result:
            print(f"\n✅ TEST PASSED: Lead event inserted successfully!")
        else:
            print(f"\n❌ TEST FAILED: Lead event insertion failed!")
            
        return result
        
    except Exception as e:
        print(f"\n💥 TEST ERROR: {str(e)}")
        logger.error(f"Error in test_single_lead_insertion: {str(e)}")
        return False


def test_multiple_lead_insertions():
    """Test inserting multiple lead events."""
    print("\n" + "="*60)
    print("🧪 TESTING: Multiple Lead Events Insertion")
    print("="*60)
    
    try:
        # Test data for multiple events
        eventos = [
            {
                "lead_id": "lead_002",
                "advogado_id": "advogado_456",
                "foi_notificado": True,
                "respondeu": True
            },
            {
                "lead_id": "lead_003",
                "advogado_id": "advogado_789",
                "foi_notificado": False,
                "respondeu": False
            },
            {
                "lead_id": "lead_004",
                "advogado_id": "advogado_123",
                "foi_notificado": True,
                "respondeu": False
            }
        ]
        
        print(f"📝 Test Data: {len(eventos)} events")
        for i, evento in enumerate(eventos, 1):
            print(f"   Event {i}: {evento['lead_id']} -> {evento['advogado_id']}")
        
        # Call the batch function
        result = bigquery_service.inserir_multiplos_eventos(eventos)
        
        if result:
            print(f"\n✅ TEST PASSED: Multiple lead events inserted successfully!")
        else:
            print(f"\n❌ TEST FAILED: Multiple lead events insertion failed!")
            
        return result
        
    except Exception as e:
        print(f"\n💥 TEST ERROR: {str(e)}")
        logger.error(f"Error in test_multiple_lead_insertions: {str(e)}")
        return False


def test_connection_verification():
    """Test BigQuery connection verification."""
    print("\n" + "="*60)
    print("🧪 TESTING: BigQuery Connection Verification")
    print("="*60)
    
    try:
        result = bigquery_service.verificar_conexao()
        
        if result:
            print(f"\n✅ TEST PASSED: BigQuery connection verified!")
        else:
            print(f"\n❌ TEST FAILED: BigQuery connection verification failed!")
            
        return result
        
    except Exception as e:
        print(f"\n💥 TEST ERROR: {str(e)}")
        logger.error(f"Error in test_connection_verification: {str(e)}")
        return False


def test_table_statistics():
    """Test getting table statistics."""
    print("\n" + "="*60)
    print("🧪 TESTING: Table Statistics Retrieval")
    print("="*60)
    
    try:
        stats = bigquery_service.obter_estatisticas_tabela()
        
        if stats:
            print(f"\n✅ TEST PASSED: Table statistics retrieved!")
            print(f"📊 Statistics:")
            print(f"   Full Table ID: {stats['full_table_id']}")
            print(f"   Number of Rows: {stats['num_rows']}")
            print(f"   Size (bytes): {stats['num_bytes']}")
            print(f"   Schema Fields: {len(stats['schema_fields'])}")
            
            print(f"\n📋 Schema:")
            for field in stats['schema_fields']:
                print(f"   - {field['name']}: {field['field_type']} ({field['mode']})")
                
            return True
        else:
            print(f"\n❌ TEST FAILED: Could not retrieve table statistics!")
            return False
            
    except Exception as e:
        print(f"\n💥 TEST ERROR: {str(e)}")
        logger.error(f"Error in test_table_statistics: {str(e)}")
        return False


def run_all_tests():
    """Run all BigQuery tests."""
    print("\n" + "="*80)
    print("🚀 STARTING BIGQUERY SERVICE TESTS")
    print("="*80)
    print(f"⏰ Test started at: {datetime.now()}")
    print(f"🗂️  Project ID: js-quiz-fiap-b1e86")
    print(f"📊 Dataset: leads_dataset")
    print(f"📋 Table: leads")
    
    # Track test results
    test_results = []
    
    # Test 1: Connection verification
    print(f"\n🔍 Running connection verification test...")
    result1 = test_connection_verification()
    test_results.append(("Connection Verification", result1))
    
    # Test 2: Table statistics
    print(f"\n📊 Running table statistics test...")
    result2 = test_table_statistics()
    test_results.append(("Table Statistics", result2))
    
    # Test 3: Single lead insertion
    print(f"\n📝 Running single lead insertion test...")
    result3 = test_single_lead_insertion()
    test_results.append(("Single Lead Insertion", result3))
    
    # Test 4: Multiple lead insertions
    print(f"\n📝 Running multiple lead insertions test...")
    result4 = test_multiple_lead_insertions()
    test_results.append(("Multiple Lead Insertions", result4))
    
    # Summary
    print("\n" + "="*80)
    print("📋 TEST RESULTS SUMMARY")
    print("="*80)
    
    passed = 0
    failed = 0
    
    for test_name, result in test_results:
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"   {test_name}: {status}")
        if result:
            passed += 1
        else:
            failed += 1
    
    print(f"\n📊 Overall Results:")
    print(f"   ✅ Passed: {passed}")
    print(f"   ❌ Failed: {failed}")
    print(f"   📈 Success Rate: {(passed/(passed+failed)*100):.1f}%")
    
    if failed == 0:
        print(f"\n🎉 ALL TESTS PASSED! BigQuery integration is working correctly.")
    else:
        print(f"\n⚠️  Some tests failed. Please check the error messages above.")
    
    print(f"\n⏰ Test completed at: {datetime.now()}")
    print("="*80)
    
    return failed == 0


if __name__ == "__main__":
    """
    Run BigQuery service tests.
    
    Usage:
        python test_bigquery.py
    """
    try:
        print("🧪 BigQuery Service Test Suite")
        print("Testing batch loading functionality for BigQuery Sandbox (free tier)")
        
        # Check if service account file exists
        if not os.path.exists("service-account.json"):
            print("❌ ERROR: service-account.json file not found in project root!")
            print("   Please ensure the service account credentials file is present.")
            sys.exit(1)
        
        # Run all tests
        success = run_all_tests()
        
        # Exit with appropriate code
        sys.exit(0 if success else 1)
        
    except KeyboardInterrupt:
        print("\n\n⏹️  Tests interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 FATAL ERROR: {str(e)}")
        logger.error(f"Fatal error in test suite: {str(e)}")
        sys.exit(1)