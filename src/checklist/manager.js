/**
 * Checklist manager: API endpoints for checklist item operations.
 * 
 * Provides endpoints for managing checklist items including splitting items
 * into multiple proposed items.
 */

const express = require('express');
const router = express.Router();

// In-memory store for items (in production, this would connect to a database)
const itemStore = new Map();
let nextItemId = 1;

/**
 * File a new item into the checklist system.
 * @param {Object} item - The item to file with text, dependsOn, repo, premium
 * @returns {Object} The filed item with assigned ID
 */
async function fileItem(item) {
  const id = `FF-${nextItemId++}`;
  const filedItem = {
    id,
    text: item.text,
    dependsOn: item.dependsOn || [],
    repo: item.repo || null,
    premium: item.premium || false,
    status: 'pending',
    filedAt: new Date().toISOString()
  };
  itemStore.set(id, filedItem);
  return filedItem;
}

/**
 * Find an item by ID
 * @param {string} id - The item ID to find
 * @returns {Object|null} The item or null if not found
 */
function findItem(id) {
  return itemStore.get(id) || null;
}

/**
 * Mark an item as superseded
 * @param {string} id - The item ID to mark
 * @returns {Object} The updated item
 */
function markSuperseded(id) {
  const item = findItem(id);
  if (!item) {
    throw new Error(`Item ${id} not found`);
  }
  item.status = 'superseded';
  item.supersededAt = new Date().toISOString();
  return item;
}

/**
 * Replace an item with new items in the store
 * @param {string} originalId - The ID of the item to replace
 * @param {Array<Object>} newItems - The new items to insert
 */
function replaceItem(originalId, newItems) {
  const original = findItem(originalId);
  if (!original) {
    throw new Error(`Original item ${originalId} not found`);
  }
  
  // Remove the original
  itemStore.delete(originalId);
  
  // Insert new items in order
  for (const item of newItems) {
    const filedItem = fileItem(item);
    itemStore.set(filedItem.id, filedItem);
  }
  
  return newItems;
}

/**
 * POST /api/checklist/items/:id/split
 * Split an item into multiple proposed items.
 * 
 * @param {string} params.id - The ID of the item to split
 * @param {Array} body.items - Array of 2-4 proposed items, each with:
 *   - text: string (required)
 *   - dependsOn: string[] (optional)
 *   - repo: string (optional)
 *   - premium: boolean (optional)
 * @returns {Object} Response with replaced item and new items
 */
router.post('/api/checklist/items/:id/split', async (req, res) => {
  try {
    const { id } = req.params;
    const { items } = req.body;
    
    // Validate items array
    if (!Array.isArray(items)) {
      return res.status(400).json({ 
        error: 'Request body must include an "items" array' 
      });
    }
    
    if (items.length < 2 || items.length > 4) {
      return res.status(400).json({ 
        error: 'Items array must contain between 2 and 4 items' 
      });
    }
    
    // Validate each item
    for (let i = 0; i < items.length; i++) {
      const item = items[i];
      if (!item.text || typeof item.text !== 'string') {
        return res.status(400).json({ 
          error: `Item ${i + 1} must have a "text" string` 
        });
      }
      if (item.dependsOn && !Array.isArray(item.dependsOn)) {
        return res.status(400).json({ 
          error: `Item ${i + 1} "dependsOn" must be an array if provided` 
        });
      }
      if (item.repo !== undefined && typeof item.repo !== 'string') {
        return res.status(400).json({ 
          error: `Item ${i + 1} "repo" must be a string if provided` 
        });
      }
      if (item.premium !== undefined && typeof item.premium !== 'boolean') {
        return res.status(400).json({ 
          error: `Item ${i + 1} "premium" must be a boolean if provided` 
        });
      }
    }
    
    // Find original item
    const originalItem = findItem(id);
    if (!originalItem) {
      return res.status(404).json({ 
        error: `Item ${id} not found` 
      });
    }
    
    // Mark original as superseded
    markSuperseded(id);
    
    // Replace original with new items
    const newItems = replaceItem(id, items);
    
    return res.status(200).json({
      replaced: originalItem,
      newItems,
      message: `Item ${id} split into ${newItems.length} items`
    });
    
  } catch (error) {
    console.error('Error in split endpoint:', error);
    return res.status(500).json({ 
      error: 'Internal server error' 
    });
  }
});

module.exports = router;
module.exports.fileItem = fileItem;
module.exports.findItem = findItem;
module.exports.markSuperseded = markSuperseded;
module.exports.replaceItem = replaceItem;
