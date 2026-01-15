#!/usr/bin/env python3
# scripts/health_check.py

import argparse
import requests
import time
import sys
import logging
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class HealthChecker:
    def __init__(self, url, timeout=300, interval=10):
        self.url = url
        self.timeout = timeout
        self.interval = interval
    
    def check_health(self):
        """Check if the application is healthy"""
        try:
            response = requests.get(self.url, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"✅ Health check passed: {data}")
                return True, data
            else:
                logger.warning(f"⚠️ Health check returned {response.status_code}")
                return False, None
                
        except requests.exceptions.RequestException as e:
            logger.warning(f"⚠️ Health check failed: {str(e)}")
            return False, None
    
    def wait_for_healthy(self):
        """Wait for application to become healthy"""
        logger.info(f"Waiting for application to be healthy at {self.url}")
        logger.info(f"Timeout: {self.timeout}s, Check interval: {self.interval}s")
        
        start_time = time.time()
        attempts = 0
        
        while True:
            attempts += 1
            elapsed = time.time() - start_time
            
            if elapsed > self.timeout:
                logger.error(f"❌ Timeout after {elapsed:.1f}s ({attempts} attempts)")
                return False
            
            logger.info(f"Attempt {attempts} (elapsed: {elapsed:.1f}s)")
            
            healthy, data = self.check_health()
            
            if healthy:
                logger.info(f"✅ Application is healthy after {elapsed:.1f}s ({attempts} attempts)")
                self.print_health_data(data)
                return True
            
            logger.info(f"Waiting {self.interval}s before next check...")
            time.sleep(self.interval)
    
    def print_health_data(self, data):
        """Print detailed health information"""
        if not data:
            return
        
        logger.info("=" * 50)
        logger.info("Health Check Details:")
        logger.info(f"  Status: {data.get('status', 'unknown')}")
        logger.info(f"  Timestamp: {data.get('timestamp', 'unknown')}")
        logger.info(f"  Uptime: {data.get('uptime', 0):.2f}s")
        logger.info(f"  Environment: {data.get('environment', 'unknown')}")
        logger.info(f"  Version: {data.get('version', 'unknown')}")
        logger.info("=" * 50)
    
    def continuous_monitoring(self, duration=3600):
        """Continuously monitor health for specified duration"""
        logger.info(f"Starting continuous health monitoring for {duration}s")
        
        start_time = time.time()
        check_count = 0
        failed_checks = 0
        
        while time.time() - start_time < duration:
            check_count += 1
            healthy, data = self.check_health()
            
            if not healthy:
                failed_checks += 1
                logger.warning(f"Failed check {failed_checks}/{check_count}")
            else:
                logger.info(f"✅ Check {check_count} passed")
            
            time.sleep(self.interval)
        
        # Summary
        success_rate = ((check_count - failed_checks) / check_count) * 100
        logger.info("=" * 50)
        logger.info("Monitoring Summary:")
        logger.info(f"  Total checks: {check_count}")
        logger.info(f"  Failed checks: {failed_checks}")
        logger.info(f"  Success rate: {success_rate:.2f}%")
        logger.info("=" * 50)
        
        return success_rate >= 95  # 95% uptime threshold
    
    def check_metrics_endpoint(self):
        """Check Prometheus metrics endpoint"""
        metrics_url = self.url.replace('/health', '/metrics')
        logger.info(f"Checking metrics endpoint: {metrics_url}")
        
        try:
            response = requests.get(metrics_url, timeout=5)
            
            if response.status_code == 200:
                metrics_count = len(response.text.split('\n'))
                logger.info(f"✅ Metrics endpoint available ({metrics_count} lines)")
                return True
            else:
                logger.warning(f"⚠️ Metrics endpoint returned {response.status_code}")
                return False
                
        except requests.exceptions.RequestException as e:
            logger.warning(f"⚠️ Metrics check failed: {str(e)}")
            return False


def main():
    parser = argparse.ArgumentParser(description='Health check utility')
    parser.add_argument('--url', required=True, 
                       help='Health check URL')
    parser.add_argument('--timeout', type=int, default=300, 
                       help='Timeout in seconds')
    parser.add_argument('--interval', type=int, default=10, 
                       help='Check interval in seconds')
    parser.add_argument('--continuous', type=int, 
                       help='Continuous monitoring duration in seconds')
    parser.add_argument('--check-metrics', action='store_true',
                       help='Also check metrics endpoint')
    
    args = parser.parse_args()
    
    checker = HealthChecker(args.url, args.timeout, args.interval)
    
    try:
        if args.continuous:
            # Continuous monitoring mode
            success = checker.continuous_monitoring(args.continuous)
            sys.exit(0 if success else 1)
        else:
            # Single health check with wait
            success = checker.wait_for_healthy()
            
            if success and args.check_metrics:
                checker.check_metrics_endpoint()
            
            sys.exit(0 if success else 1)
            
    except KeyboardInterrupt:
        logger.info("\n⚠️ Health check interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        sys.exit(1)


if __name__ == '__main__':
    main()